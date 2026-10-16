#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""P1 manual runner proof: saved snapshot integrity and a small R2 round trip."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = ("20261015.1247", "20261015.1430")
BASELINE_RAW = "a6cf00fbe4f4f6fbd4b297f20ce24e035cbcdc2b40b3d56687fc3250012841b0"
BASELINE_CHANNEL = "090d163fa605545dbe0bacbbdfe57e7a0784037c64ece48a74f23d3841e1604d"


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def checksums(path):
    selected = {}
    for line in path.read_text().splitlines():
        match = re.fullmatch(r"([0-9a-f]{64}) [ *]([^\r\n]+)", line)
        if not match:
            raise ValueError("malformed SHA256SUMS")
        digest, name = match.groups()
        if name in (".", "..") or any(c in name for c in ("/", "\\", "\x00")) or name in selected:
            raise ValueError("unsafe or duplicate checksum filename")
        selected[name] = digest
    if not selected:
        raise ValueError("empty SHA256SUMS")
    return selected


def verify_files(directory, selected):
    for name, expected in selected.items():
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"missing or non-regular artifact: {name}")
        if sha256(path) != expected:
            raise ValueError(f"artifact hash mismatch: {name}")


def verify_signature(channel, keyring):
    with tempfile.TemporaryDirectory(prefix="beamline-gpgv-") as home:
        result = subprocess.run(["gpgv", "--homedir", home, "--keyring", str(keyring),
                                 str(channel / "SHA256SUMS.gpg"), str(channel / "SHA256SUMS")],
                                capture_output=True)
    if result.returncode:
        raise ValueError("channel signature verification failed")


def raw_installer_hash(compressed):
    with subprocess.Popen(["zstd", "-q", "-d", "-c", str(compressed)],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
        digest = hashlib.file_digest(process.stdout, "sha256").hexdigest()
        if process.wait() != 0:
            raise ValueError("installer decompression failed")
    return digest


def verify_snapshot(directory, snapshot, keyring):
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest.get("snapshot") != snapshot or manifest.get("result") != "green" or manifest.get("arch") != ["aarch64"]:
        raise ValueError("saved snapshot identity, result or architecture differs")
    root_sums = checksums(directory / "SHA256SUMS")
    verify_files(directory, root_sums)
    channel = directory / "update"
    verify_signature(channel, keyring)
    channel_sums = checksums(channel / "SHA256SUMS")
    actual_files = {p.name for p in channel.iterdir()}
    if actual_files != set(channel_sums) | {"SHA256SUMS", "SHA256SUMS.gpg"}:
        raise ValueError("channel contains unlisted or missing artifacts")
    if any(snapshot not in name for name in channel_sums):
        raise ValueError("channel mixes snapshot versions")
    verify_files(channel, channel_sums)
    raw_name = "virt-aarch64.install.raw"
    installer = manifest.get("artifacts", {}).get(raw_name, {})
    compressed_name = raw_name + ".zst"
    if installer.get("zst") != compressed_name or root_sums.get(compressed_name) != installer.get("zst_sha256"):
        raise ValueError("installer manifest and checksums disagree")
    raw_digest = raw_installer_hash(directory / compressed_name)
    if raw_digest != installer.get("sha256"):
        raise ValueError("uncompressed installer hash mismatch")
    channel_digest = sha256(channel / "SHA256SUMS")
    if snapshot == SNAPSHOTS[1] and (raw_digest != BASELINE_RAW or channel_digest != BASELINE_CHANNEL):
        raise ValueError("P0 baseline identity changed")
    return {"snapshot": snapshot, "arch": "aarch64", "channel_files": len(channel_sums),
            "channel_sha256": channel_digest, "installer_sha256": raw_digest,
            "installer_zst_sha256": installer["zst_sha256"], "signature": "valid"}


def r2_round_trip(account, bucket, public_url, progress=None):
    if not re.fullmatch(r"[0-9a-f]{32}", account):
        raise ValueError("R2_ACCOUNT_ID must contain 32 lowercase hexadecimal characters")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", bucket):
        raise ValueError("invalid R2_BUCKET")
    parsed = urllib.parse.urlsplit(public_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("R2 public URL must use HTTPS without credentials, query or fragment")
    environment = dict(os.environ)
    for name in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_SESSION_TOKEN", "AWS_SECURITY_TOKEN"):
        environment.pop(name, None)
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        if not environment.get(name):
            raise ValueError(f"missing {name}; inject the corresponding GitHub R2 secret")
    run = os.environ.get("GITHUB_RUN_ID", "local")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    if not re.fullmatch(r"[A-Za-z0-9-]+", run) or not attempt.isdigit():
        raise ValueError("invalid smoke run identity")
    key = f"p1/smoke/{run}-{attempt}/{uuid.uuid4().hex}.txt"
    payload = ("Beamline P1 R2 smoke test\n" + key + "\n").encode()
    progress = {} if progress is None else progress
    progress.update(key=key, bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest(),
                    s3_write="pending", s3_read="pending", public_read="pending")
    with tempfile.TemporaryDirectory(prefix="beamline-r2-smoke-") as temp:
        work = Path(temp)
        # Do not inherit the Mac owner's AWS profiles or credential files.
        (work / "aws-empty").touch()
        environment.update(AWS_CONFIG_FILE=str(work / "aws-empty"),
                           AWS_SHARED_CREDENTIALS_FILE=str(work / "aws-empty"),
                           AWS_EC2_METADATA_DISABLED="true", AWS_REGION="auto", AWS_DEFAULT_REGION="auto",
                           AWS_PAGER="", AWS_RETRY_MODE="standard", AWS_MAX_ATTEMPTS="3",
                           AWS_REQUEST_CHECKSUM_CALCULATION="when_required",
                           AWS_RESPONSE_CHECKSUM_VALIDATION="when_required")
        command = ["aws", "--endpoint-url", f"https://{account}.r2.cloudflarestorage.com",
                   "--region", "auto", "--no-cli-pager", "s3api"]
        def aws(operation, *args):
            result = subprocess.run(command + [operation, "--bucket", bucket, "--key", key, *args],
                                    env=environment, capture_output=True, timeout=90)
            if result.returncode:
                code = re.search(rb"\(([^)]+)\) when calling", result.stderr)
                detail = code[1].decode(errors="replace") if code else f"exit {result.returncode}"
                raise ValueError(f"R2 {operation} failed ({detail})")
            return result.stdout
        (work / "upload.txt").write_bytes(payload)
        aws("put-object", "--body", str(work / "upload.txt"), "--content-type", "text/plain", "--cache-control", "no-store")
        progress["s3_write"] = "passed"
        head = json.loads(aws("head-object"))
        if head.get("ContentLength") != len(payload):
            raise ValueError("R2 object size differs")
        aws("get-object", str(work / "download.txt"))
        if (work / "download.txt").read_bytes() != payload:
            raise ValueError("R2 S3 download differs")
        progress["s3_read"] = "passed"
        url = public_url.rstrip("/") + "/" + key
        request = urllib.request.Request(url, headers={"User-Agent": "beamline-p1-smoke/1"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.status != 200 or response.read(len(payload) + 1) != payload:
                    raise ValueError("public R2 download differs")
        except urllib.error.HTTPError as exc:
            raise ValueError(f"public R2 read failed (HTTP {exc.code})") from None
        progress["public_read"] = "passed"
    return progress


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots-only", action="store_true", help="verify saved inputs without R2 access")
    parser.add_argument("--snapshot-root", type=Path, default=os.environ.get("BEAMLINE_SNAPSHOT_ROOT"))
    parser.add_argument("--report", type=Path, default=ROOT / "out/p1/smoke.json")
    args = parser.parse_args()
    report = {"schema": 1, "result": "failed", "snapshots": [], "r2": None}
    try:
        if args.snapshot_root is None:
            raise ValueError("set BEAMLINE_SNAPSHOT_ROOT to the preserved snapshot directory")
        for command in ("gpgv", "zstd") + (() if args.snapshots_only else ("aws",)):
            if not shutil.which(command):
                raise ValueError(f"required command is missing: {command}")
        for snapshot in SNAPSHOTS:
            print(f"Verifying saved snapshot {snapshot}", flush=True)
            report["snapshots"].append(verify_snapshot(args.snapshot_root / snapshot, snapshot,
                ROOT / "files/keys/dev/update/import-pubring.pgp"))
        if not args.snapshots_only:
            report["r2"] = {}
            r2_round_trip(os.environ.get("R2_ACCOUNT_ID", ""), os.environ.get("R2_BUCKET", ""),
                          os.environ.get("R2_PUBLIC_URL", "https://store.beamlineos.org"), report["r2"])
        report["result"] = "passed"
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        # Avoid publishing local filesystem paths, endpoints, profiles or credential values.
        report["error"] = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
