#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
HELP = """P1 manual runner proof: saved snapshot integrity and a small R2 round trip."""

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
from snapshot import (SNAPSHOTS, BASELINE_RAW, BASELINE_CHANNEL, sha256, checksums,
                      verify_files, verify_signature, raw_installer_hash, verify_snapshot)


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
    parser = argparse.ArgumentParser(description=HELP)
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
                                                                                            
        report["error"] = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
