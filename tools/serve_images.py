#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Serve signed immutable publications through desync/FUSE and a local Caddy.

Run as the same unprivileged user for FUSE and backend Caddy. The owner's public
Caddy reverse-proxies this localhost backend. No store credentials are used.
Mutable channels and signed pointer reconciliation are separate work.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time
import urllib.parse

from desync_tool import install
from publish import public_get, safe_path, validate_manifest, verify_manifest_signature, checks, KEYRING


def keep_file(path, data):
    """An existing signed release's local metadata is immutable too."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or (path.exists() and path.read_bytes() != data):
        raise ValueError(f"local immutable metadata conflict: {path.name}")
    if not path.exists():
        path.write_bytes(data)


def fetch_release(base, snapshot, destination):
    prefix = f"snapshots/{snapshot}/aarch64/"
    # Authenticate the manifest before accepting any paths or index hashes from it.
    with tempfile.TemporaryDirectory(prefix="beamline-images-metadata-") as temporary:
        package = Path(temporary)
        for name in ("publication.json", "publication.json.gpg"):
            (package / name).write_bytes(public_get(base, prefix + name))
        verify_manifest_signature(package)
        manifest = validate_manifest(json.loads((package / "publication.json").read_bytes()), snapshot)
        names = dict(manifest["metadata"])
        names.update({a["index"]: a["index_sha256"] for a in manifest["artifacts"].values()})
        for name, digest in names.items():
            data = public_get(base, prefix + safe_path(name))
            if hashlib.sha256(data).hexdigest() != digest:
                raise ValueError(f"public metadata digest mismatch: {name}")
            target = package / name
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(data)
        checks.verify_signature(package / "update", KEYRING)
        selected = checks.checksums(package / "update/SHA256SUMS")
        declared = {name.removeprefix("update/"): a["sha256"] for name, a in manifest["artifacts"].items()
                    if name.startswith("update/")}
        if selected != declared or any(snapshot not in name for name in selected):
            raise ValueError("publication disagrees with its signed channel")
        for name in [*names, "publication.json.gpg", "publication.json"]:
            keep_file(destination / name, (package / name).read_bytes())
    return manifest


def cache_files(store):
    return [p for p in store.glob("????/*.cacnk") if not p.is_symlink() and not p.parent.is_symlink()
            and re.fullmatch(r"[0-9a-f]{64}\.cacnk", p.name) and p.name.startswith(p.parent.name)]


def evict_cache(store, maximum):
    """Insertion-age eviction; desync v1.1.4 does not touch mtimes on cache hits.

    Unlinking a chunk is safe while readers have it open. Missing chunks refetch;
    desync writes replacements by atomic rename. Ignore its temporary files.
    """
    held = []
    for path in cache_files(store):
        try:
            stat = path.stat()
            held.append((stat.st_mtime_ns, stat.st_size, path))
        except FileNotFoundError:
            pass
    size = sum(item[1] for item in held)
    removed = 0
    if size > maximum:
        for _, length, path in sorted(held):
            if size <= maximum * 4 // 5:
                break
            try:
                path.unlink()
            except FileNotFoundError:
                continue
            size -= length
            removed += 1
    return {"cache_bytes": size, "evicted_chunks": removed}


def caddy_config(site, paths, address):
    """Set strong ETags before file_server handles conditional/range requests."""
    lines = ["{", "    admin off", "    auto_https off", "}", f"http://{address} {{",
             "    header Cache-Control no-store",
             "    respond /healthz 200"]
    for name, digest in sorted(paths.items()):
        lines.extend([f"    route {json.dumps('/' + name)} {{",
                      "        header ETag " + json.dumps('"sha256-' + digest + '"'),
                      # Separate header handlers: only deletion is deferred. Defer the ETag
                      # itself and Go's If-Range check would see a different validator.
                      "        header -Last-Modified",
                      "        request_header -If-Modified-Since",
                      "        request_header -If-Unmodified-Since",
                      "        header {", '            Cache-Control "public, max-age=31536000, immutable"',
                      "            match status 200 206 304", "        }",
                      f"        root * {json.dumps(str(site))}", "        file_server", "    }"])
    lines.extend(["    respond 404", "    handle_errors {", "        header -ETag", "        header Cache-Control no-store",
                  "        respond {err.status_code}", "    }", "}"])
    return "\n".join(lines) + "\n"


def prepare(base, snapshots, state, address):
    site, mounts = state / "site", state / "mounts"
    site.mkdir(exist_ok=True)
    mounts.mkdir(exist_ok=True)
    blobs, paths = {}, {}
    for snapshot in snapshots:
        relative = Path("snapshots") / snapshot / "aarch64"
        package = state / "metadata" / snapshot / "aarch64"
        manifest = fetch_release(base, snapshot, package)
        for name, artifact in manifest["artifacts"].items():
            digest = artifact["sha256"]
            mount = mounts / digest
            mount.mkdir(exist_ok=True)
            blobs.setdefault(digest, (package / artifact["index"], mount, artifact["size"]))
            target = site / relative / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink():
                if target.readlink() != mount / digest:
                    raise ValueError("existing virtual image points at different content")
            elif target.exists():
                raise ValueError("existing virtual image is not a symlink")
            else:
                target.symlink_to(mount / digest)
            paths[str(relative / name)] = digest
        for name in (*manifest["metadata"], "publication.json", "publication.json.gpg"):
            data = (package / name).read_bytes()
            keep_file(site / relative / name, data)
            paths[str(relative / name)] = hashlib.sha256(data).hexdigest()
    configuration = state / "Backend.Caddyfile"
    configuration.write_text(caddy_config(site, paths, address))
    return blobs, configuration


def serve(args, state, cache):
    if os.uname().sysname != "Linux" or not Path("/dev/fuse").exists():
        raise ValueError("serving requires Linux with /dev/fuse and fusermount3")
    if not shutil.which("fusermount3") or not shutil.which(args.caddy):
        raise ValueError("install fusermount3 and Caddy before starting the backend")
    binary = install(cache)
    blobs, configuration = prepare(args.public_url, args.snapshots, state, args.listen)
    subprocess.run([args.caddy, "validate", "--config", str(configuration), "--adapter", "caddyfile"], check=True)
    store = cache / "store"
    store.mkdir(exist_ok=True)
    config = state / "desync.json"
    config.write_text("{}\n")
    command = [str(binary), "--config", str(config), "--digest", "sha512-256"]
    if args.prewarm:
        subprocess.run(command + ["cache", "-n", "16", "-s", args.public_url.rstrip("/") + "/store/",
                                  "-c", str(store), *[str(blob[0]) for blob in blobs.values()]], check=True)
        if sum(p.stat().st_size for p in cache_files(store)) > args.cache_bytes:
            raise ValueError("prewarmed working set exceeds cache high-water mark; increase --cache-bytes")
    processes = []
    stopping = False
    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, stop)
    try:
        for digest, (index, mount, size) in blobs.items():
            if os.path.ismount(mount):
                subprocess.run(["fusermount3", "-u", "-z", str(mount)], check=True)
            process = subprocess.Popen(command + ["mount-index", "-s", args.public_url.rstrip("/") + "/store/",
                                                   "-c", str(store), str(index), str(mount)])
            processes.append(process)
            deadline = time.monotonic() + 30
            while not os.path.ismount(mount):
                if stopping or process.poll() is not None or time.monotonic() > deadline:
                    raise ValueError("virtual image mount did not become ready")
                time.sleep(.05)
            if (mount / digest).stat().st_size != size:
                raise ValueError("virtual image size disagrees with signed publication")
        process = subprocess.Popen([args.caddy, "run", "--config", str(configuration), "--adapter", "caddyfile"])
        processes.append(process)
        print(json.dumps({"phase": "serving", "snapshots": args.snapshots, "unique_mounts": len(blobs),
                          "listen": args.listen, "cache_high_water_bytes": args.cache_bytes}), flush=True)
        while not stopping:
            if any(p.poll() is not None for p in processes):
                raise ValueError("a FUSE mount or the backend Caddy exited")
            statistics = evict_cache(store, args.cache_bytes)
            if statistics["evicted_chunks"]:
                print(json.dumps(statistics), flush=True)
            for _ in range(50):
                if stopping:
                    break
                time.sleep(.1)
    finally:
        # Stop accepting HTTP before dismantling any mounted blobs.
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
        for process in reversed(processes):
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for _, mount, _ in blobs.values():
            if os.path.ismount(mount):
                subprocess.run(["fusermount3", "-u", "-z", str(mount)], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshots", nargs="+")
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--listen", default="127.0.0.1:9080")
    parser.add_argument("--public-url", default="https://store.beamlineos.org")
    parser.add_argument("--cache-bytes", type=int, default=8 << 30)
    parser.add_argument("--caddy", default="caddy")
    parser.add_argument("--prewarm", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    try:
        if any(not re.fullmatch(r"\d{8}\.\d{4}", name) for name in args.snapshots):
            raise ValueError("snapshot must be YYYYMMDD.HHMM")
        if not re.fullmatch(r"127\.0\.0\.1:[0-9]{1,5}", args.listen) or not 0 < int(args.listen.split(":")[1]) < 65536:
            raise ValueError("backend must listen on an explicit localhost port")
        parsed = urllib.parse.urlsplit(args.public_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("public store URL must be HTTPS without credentials, query or fragment")
        if args.cache_bytes < 256 << 20:
            raise ValueError("cache high-water mark must be at least 256 MiB")
        state, cache = args.state_root.resolve(), args.cache_root.resolve()
        for directory in (state, cache):
            directory.mkdir(parents=True, exist_ok=True)
        with (state / "serve.lock").open("a") as state_lock, (cache / "serve.lock").open("a") as cache_lock:
            for lock in (state_lock, cache_lock):
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.prepare_only:
                blobs, configuration = prepare(args.public_url, args.snapshots, state, args.listen)
                print(json.dumps({"unique_mounts": len(blobs), "configuration": str(configuration)}))
            else:
                serve(args, state, cache)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"serve-images: {exc}\n")


if __name__ == "__main__":
    main()
