#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Publish immutable, verified saved snapshots to the shared R2 chunk store.

ci/publish SNAPSHOT --prepare-only      validate and index without cloud credentials
ci/publish SNAPSHOT [--repeat]          upload, verify through public HTTP, commit manifest
ci/publish SNAPSHOT --verify-only      reconstruct the signed public release without inputs
ci/publish --refresh-page              rebuild only the HTML index from committed publications
"""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

from desync_tool import VERSION, install
import snapshot as checks
from publication import canonical, safe_path, validate_manifest, verify_manifest_signature

ROOT = Path(__file__).resolve().parents[1]
KEYRING = ROOT / "files/keys/dev/update/import-pubring.pgp"



def public_get(base, key):
    request = urllib.request.Request(base.rstrip("/") + "/" + safe_path(key),
                                     headers={"User-Agent": "beamline-publish/1"})
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            if response.status != 200:
                raise ValueError("unexpected public store response")
            return response.read(16 << 20)
    except urllib.error.HTTPError as exc:
        raise ValueError(f"public read failed (HTTP {exc.code}): {key}") from None


class R2:
    """Small-object conditional writes; desync handles chunk transfer concurrency."""

    def __init__(self, work):
        account, self.bucket = os.environ.get("R2_ACCOUNT_ID", ""), os.environ.get("R2_BUCKET", "")
        if not re.fullmatch(r"[0-9a-f]{32}", account) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", self.bucket):
            raise ValueError("configure R2_ACCOUNT_ID and R2_BUCKET")
        self.env = dict(os.environ)
        for key in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_SESSION_TOKEN", "AWS_SECURITY_TOKEN",
                    "S3_ACCESS_KEY", "S3_SECRET_KEY", "S3_SESSION_TOKEN", "S3_REGION"):
            self.env.pop(key, None)
        if not all(self.env.get(k) for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")):
            raise ValueError("inject the GitHub R2 writer secrets")
        empty = work / "empty-aws-config"
        empty.touch()
        self.env.update(AWS_CONFIG_FILE=str(empty), AWS_SHARED_CREDENTIALS_FILE=str(empty),
                        AWS_EC2_METADATA_DISABLED="true", AWS_REGION="auto", AWS_DEFAULT_REGION="auto", AWS_PAGER="",
                        AWS_MAX_ATTEMPTS="3", AWS_RETRY_MODE="standard", AWS_REQUEST_CHECKSUM_CALCULATION="when_required",
                        AWS_RESPONSE_CHECKSUM_VALIDATION="when_required", S3_REGION="auto")
        self.endpoint = f"https://{account}.r2.cloudflarestorage.com"
        self.store = f"s3+{self.endpoint}/{self.bucket}/store?lookup=path"
        self.work = work

    def call(self, operation, *args, missing=False, conditional=False):
        command = ["aws", "--endpoint-url", self.endpoint, "--region", "auto", "--no-cli-pager",
                   "s3api", operation, "--bucket", self.bucket, *args]
        result = subprocess.run(command, env=self.env, capture_output=True, timeout=120)
        if result.returncode:
            found = re.search(rb"\(([^)]+)\) when calling", result.stderr)
            code = found[1].decode(errors="replace") if found else f"exit {result.returncode}"
            if missing and code in ("NoSuchKey", "404", "NotFound"):
                return None
            if conditional and code in ("PreconditionFailed", "412", "ConditionalRequestConflict"):
                return None
            raise ValueError(f"R2 {operation} failed ({code})")
        return result.stdout

    def get(self, key):
        dest = self.work / "object-download"
        result = self.call("get-object", "--key", safe_path(key), str(dest), missing=True)
        return None if result is None else dest.read_bytes()

    def put(self, key, data):
        existing = self.get(key)
        if existing is not None:
            if existing != data:
                raise ValueError(f"immutable object conflict: {key}")
            return False
        body = self.work / "object-upload"
        body.write_bytes(data)
        result = self.call("put-object", "--key", safe_path(key), "--body", str(body), "--if-none-match", "*",
                           "--cache-control", "public, max-age=31536000, immutable", conditional=True)
        if self.get(key) != data:
            raise ValueError(f"immutable object conflict after conditional write: {key}")
        return result is not None

    def chunks(self):
        result = json.loads(self.call("list-objects-v2", "--prefix", "store/"))
        return {x["Key"]: x["Size"] for x in result.get("Contents", []) or []}

    def publications(self):
        result = json.loads(self.call("list-objects-v2", "--prefix", "snapshots/"))
        return [x["Key"] for x in result.get("Contents", []) or [] if x["Key"].endswith("/publication.json")]

    def version(self, key):
        dest = self.work / "page-download"
        result = self.call("get-object", "--key", safe_path(key), str(dest), missing=True)
        return (None, None) if result is None else (dest.read_bytes(), json.loads(result)["ETag"])

    def replace_page(self, key, data, etag):
        body = self.work / "page-upload"
        body.write_bytes(data)
        condition = ("--if-match", etag) if etag is not None else ("--if-none-match", "*")
        result = self.call("put-object", "--key", safe_path(key), "--body", str(body), *condition,
                           "--content-type", "text/html; charset=utf-8", "--cache-control", "public, max-age=60",
                           conditional=True)
        return result is not None


def sign_manifest(path):
    with tempfile.TemporaryDirectory(prefix="beamline-publish-gpg-") as home:
        command = ["gpg", "--homedir", home, "--batch", "--quiet"]
        subprocess.run(command + ["--import", str(ROOT / "files/keys/dev/update/update-signing.sec.asc")],
                       check=True, capture_output=True)
        records = subprocess.run(command + ["--with-colons", "--list-secret-keys"], check=True,
                                 capture_output=True, text=True).stdout
        created = next(line.split(":")[5] for line in records.splitlines() if line.startswith("sec:"))
        subprocess.run(command + ["--faked-system-time", created + "!", "--digest-algo", "SHA256",
                                 "--detach-sign", "--output", str(path) + ".gpg", str(path)],
                       check=True, capture_output=True)


def run_desync(binary, config, *args, env=None, tick=None):
    command = [str(binary), "--config", str(config), "--digest", "sha512-256", *map(str, args)]
    with subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL) as process:
        started = time.monotonic()
        while True:
            try:
                status = process.wait(timeout=30)
                break
            except subprocess.TimeoutExpired:
                elapsed = int(time.monotonic() - started)
                print(f"desync {args[0]} running ({elapsed}s)", flush=True)
                if tick:
                    tick()
        if status:
            raise ValueError(f"desync {args[0]} failed (exit {status})")


def prepare(snapshot_root, snapshot, cache, binary, config):
    source = snapshot_root / snapshot
    validation = checks.verify_snapshot(source, snapshot, KEYRING)
    store = cache / "store"
    store.mkdir(exist_ok=True)
    package = cache / "prepared" / snapshot / "aarch64"
    package.mkdir(parents=True, exist_ok=True)
    artifacts = {}
    selected = {"update/" + name: (source / "update" / name, digest)
                for name, digest in checks.checksums(source / "update/SHA256SUMS").items()}
    installer = "virt-aarch64.install.raw.zst"
    selected[installer] = source / installer, validation["installer_zst_sha256"]
    indexes = {}
    for name, (path, digest) in sorted(selected.items()):
        index = f"indexes/{digest}.caibx"
        if index not in indexes:
            print(f"Indexing {name}", flush=True)
            target = package / index
            target.parent.mkdir(exist_ok=True)
            # Recreate deterministically; make reuses valid chunks in the local store.
            run_desync(binary, config, "make", "-m", "16:64:256", "-n", "16", "-s", store, target, path)
            indexes[index] = checks.sha256(target)
        artifacts[name] = {"sha256": digest, "size": path.stat().st_size,
                           "index": index, "index_sha256": indexes[index]}
    metadata = {}
    for name in ("SHA256SUMS", "SHA256SUMS.gpg"):
        data = (source / "update" / name).read_bytes()
        target = package / "update" / name
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(data)
        metadata["update/" + name] = hashlib.sha256(data).hexdigest()
    manifest = {"schema": 1, "snapshot": snapshot, "arch": "aarch64",
                "chunking": {"desync_version": VERSION, "digest": "sha512-256", "sizes_kib": [16, 64, 256], "store": "store/"},
                "installer_uncompressed_sha256": validation["installer_sha256"],
                "artifacts": artifacts, "metadata": metadata}
    marker = package / "publication.json"
    wanted = canonical(manifest)
    if marker.exists() and marker.read_bytes() != wanted:
        raise ValueError("saved snapshot differs from its existing prepared publication")
    marker.write_bytes(wanted)
    marker.with_suffix(".json.gpg").unlink(missing_ok=True)
    sign_manifest(marker)
    verify_manifest_signature(package)
    return package, manifest


def package_files(package, manifest):
    paths = set(manifest["metadata"]) | {a["index"] for a in manifest["artifacts"].values()}
    return {name: (package / safe_path(name)).read_bytes() for name in sorted(paths)}


def verify_public_metadata(package, manifest, base):
    snapshot = manifest["snapshot"]
    validate_manifest(manifest, snapshot)
    prefix = f"snapshots/{snapshot}/aarch64/"
    for name, data in package_files(package, manifest).items():
        if public_get(base, prefix + name) != data:
            raise ValueError(f"public metadata differs: {name}")
    checks.verify_signature(package / "update", KEYRING)
    selected = checks.checksums(package / "update/SHA256SUMS")
    declared = {name.removeprefix("update/"): artifact["sha256"]
                for name, artifact in manifest["artifacts"].items() if name.startswith("update/")}
    if selected != declared or any(snapshot not in name for name in declared):
        raise ValueError("publication disagrees with the signed channel")
    return len(package_files(package, manifest))


def verify_public(package, manifest, base, binary, config, progress, concurrency=64):
    verify_public_metadata(package, manifest, base)
    verified = set()
    with tempfile.TemporaryDirectory(prefix="beamline-publish-extract-") as temp:
        target = Path(temp) / "artifact"
        for name, artifact in sorted(manifest["artifacts"].items()):
            if artifact["sha256"] in verified:
                continue
            progress(phase="verify-public", verifying=name, verified_unique_blobs=len(verified))
            print(f"Reconstructing from public chunks: {name}", flush=True)
            run_desync(binary, config, "extract", "-n", concurrency, "-s", base.rstrip("/") + "/store/",
                       package / artifact["index"], target, tick=lambda: progress())
            if target.stat().st_size != artifact["size"] or checks.sha256(target) != artifact["sha256"]:
                raise ValueError(f"reconstructed artifact differs: {name}")
            if name == "virt-aarch64.install.raw.zst" and checks.raw_installer_hash(target) != manifest["installer_uncompressed_sha256"]:
                raise ValueError("reconstructed installer raw digest differs")
            target.unlink()
            verified.add(artifact["sha256"])
    return {"verified_artifacts": len(manifest["artifacts"]), "verified_unique_blobs": len(verified)}


def publish(package, manifest, remote, replicate, verify):
    """Preflight conflicts, transfer, verify, then create the signed commit marker last."""
    prefix = f"snapshots/{manifest['snapshot']}/aarch64/"
    data = package_files(package, manifest)
    signature = (package / "publication.json.gpg").read_bytes()
    marker = canonical(manifest)
    all_objects = dict(data, **{"publication.json.gpg": signature, "publication.json": marker})
    for name, wanted in all_objects.items():
        held = remote.get(prefix + name)
        if held is not None and held != wanted:
            raise ValueError(f"immutable object conflict: {prefix + name}")
    before = remote.chunks()
    replicate(before)
    after = remote.chunks()
    uploaded = sum(remote.put(prefix + name, wanted) for name, wanted in data.items())
    verification = verify()
    # Readers treat publication.json as the commit marker. Its signature already exists.
    uploaded += remote.put(prefix + "publication.json.gpg", signature)
    uploaded += remote.put(prefix + "publication.json", marker)
    return dict(verification, chunks_added=len(after.keys() - before.keys()),
                chunk_bytes_added=sum(after[k] for k in after.keys() - before.keys()),
                store_chunks=len(after), store_bytes=sum(after.values()), metadata_uploaded=uploaded)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("snapshot", nargs="?")
    parser.add_argument("--snapshot-root", type=Path, default=os.environ.get("BEAMLINE_SNAPSHOT_ROOT"))
    parser.add_argument("--cache-root", type=Path)
    parser.add_argument("--public-url", default="https://store.beamlineos.org")
    parser.add_argument("--report", type=Path, default=ROOT / "out/publish/report.json")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare-only", action="store_true")
    mode.add_argument("--verify-only", action="store_true")
    mode.add_argument("--refresh-page", action="store_true", help="update only the static download index; no image transfer")
    parser.add_argument("--repeat", action="store_true", help="repeat publication and require zero new objects")
    parser.add_argument("--upload-concurrency", type=int, default=128)
    parser.add_argument("--download-concurrency", type=int, default=64)
    args = parser.parse_args()
    report = {"schema": 1, "snapshot": args.snapshot, "result": "running", "phase": "prepare",
              "download_concurrency": args.download_concurrency}
    def progress(**values):
        report.update(values)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_bytes(canonical(report))
    try:
        if not args.refresh_page and not re.fullmatch(r"\d{8}\.\d{4}", args.snapshot or ""):
            raise ValueError("snapshot must be YYYYMMDD.HHMM")
        if args.refresh_page and (args.snapshot or args.repeat):
            raise ValueError("--refresh-page takes no snapshot or --repeat")
        if not 1 <= args.upload_concurrency <= 256:
            raise ValueError("upload concurrency must be between 1 and 256")
        if not 1 <= args.download_concurrency <= 256:
            raise ValueError("download concurrency must be between 1 and 256")
        if not args.public_url.startswith("https://") or "?" in args.public_url or "#" in args.public_url or "@" in args.public_url:
            raise ValueError("public store URL must be HTTPS without credentials, query or fragment")
        if not args.verify_only and not args.refresh_page and args.snapshot_root is None:
            raise ValueError("set BEAMLINE_SNAPSHOT_ROOT")
        cache = (args.cache_root or (args.snapshot_root.parent / "publish-cache" if args.snapshot_root else ROOT / "out/publish-cache")).resolve()
        cache.mkdir(parents=True, exist_ok=True)
        with (cache / "publish.lock").open("a") as lock, tempfile.TemporaryDirectory(prefix="beamline-publish-") as temp:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError("another publisher owns the local publication cache") from exc
            work = Path(temp)
            config = work / "desync.json"
            config.write_text("{}\n")
            binary = None if args.refresh_page else install(cache)
            progress()
            if args.refresh_page:
                from image_page import refresh
                progress(phase="refresh-page")
                report["download_page"] = refresh(R2(work))
            elif args.verify_only:
                package = work / "release"
                package.mkdir()
                prefix = f"snapshots/{args.snapshot}/aarch64/"
                for name in ("publication.json", "publication.json.gpg"):
                    (package / name).write_bytes(public_get(args.public_url, prefix + name))
                verify_manifest_signature(package)
                manifest = validate_manifest(json.loads((package / "publication.json").read_bytes()), args.snapshot)
                names = dict(manifest["metadata"])
                names.update({a["index"]: a["index_sha256"] for a in manifest["artifacts"].values()})
                for name, digest in names.items():
                    data = public_get(args.public_url, prefix + safe_path(name))
                    if hashlib.sha256(data).hexdigest() != digest:
                        raise ValueError(f"public index/metadata digest mismatch: {name}")
                    target = package / name
                    target.parent.mkdir(exist_ok=True)
                    target.write_bytes(data)
                report["verification"] = verify_public(package, manifest, args.public_url, binary, config, progress,
                                                       args.download_concurrency)
            else:
                package, manifest = prepare(args.snapshot_root, args.snapshot, cache, binary, config)
                progress(phase="prepared", artifacts=len(manifest["artifacts"]))
                if not args.prepare_only:
                    remote = R2(work)
                    indexes = sorted({str(package / a["index"]) for a in manifest["artifacts"].values()})
                    def replicate(existing):
                        # The complete S3 inventory is already available. Avoid a separate
                        # HEAD for every existing chunk, especially on repeat publication.
                        ignore = work / "existing-chunks.txt"
                        ids = {key.rsplit("/", 1)[1].removesuffix(".cacnk") for key in existing
                               if re.fullmatch(r"store/([0-9a-f]{4})/\1[0-9a-f]{60}\.cacnk", key)}
                        ignore.write_text("".join(chunk + "\n" for chunk in sorted(ids)))
                        progress(phase="upload-chunks", existing_store_chunks=len(existing),
                                 upload_concurrency=args.upload_concurrency)
                        run_desync(binary, config, "cache", "-n", args.upload_concurrency,
                                   "--ignore-chunks", ignore, "-s", cache / "store", "-c", remote.store,
                                   *indexes, env=remote.env, tick=lambda: progress())
                    def verify():
                        return verify_public(package, manifest, args.public_url, binary, config, progress,
                                             args.download_concurrency)
                    report["publication"] = publish(package, manifest, remote, replicate, verify)
                    if args.repeat:
                        def verify_repeat():
                            # This invocation has just reconstructed every immutable blob.
                            # Repeat cloud operations and recheck public metadata; separate
                            # invocations still reconstruct the complete artifact set.
                            progress(phase="verify-repeat-metadata")
                            count = verify_public_metadata(package, manifest, args.public_url)
                            prefix = f"snapshots/{args.snapshot}/aarch64/"
                            for name in ("publication.json.gpg", "publication.json"):
                                if public_get(args.public_url, prefix + name) != (package / name).read_bytes():
                                    raise ValueError(f"public commit marker differs: {name}")
                            return {"verified_metadata": count + 2, "body_verification": "reused first pass in same invocation"}
                        report["repeat"] = publish(package, manifest, remote, replicate, verify_repeat)
                        if report["repeat"]["chunks_added"] or report["repeat"]["metadata_uploaded"]:
                            raise ValueError("repeat publication unexpectedly created objects")
                    report["publication_url"] = args.public_url.rstrip("/") + f"/snapshots/{args.snapshot}/aarch64/publication.json"
                    from image_page import refresh
                    progress(phase="refresh-page")
                    report["download_page"] = refresh(remote)
            progress(result="passed", phase="complete")
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        progress(result="failed", error=str(exc) if isinstance(exc, ValueError) else type(exc).__name__)
    print(json.dumps(report, indent=2), flush=True)
    return 0 if report["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
