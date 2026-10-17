#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
                                                                                            
import hashlib
import json
import os
from pathlib import Path
import platform
import time
import urllib.parse
import urllib.error
import urllib.request

from publication import USER_AGENT, validate_manifest, verify_manifest_signature

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = "20261015.1430"


def origin(value):
    url = urllib.parse.urlsplit(value)
    if url.scheme != "https" or not url.netloc or url.username or url.password or url.query or url.fragment or url.path not in ("", "/"):
        raise ValueError("Benchmark requires an HTTPS origin")
    return value.rstrip("/")


def measure(url, headers, size, sha256=None, bounds=None):
    started = time.monotonic()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})
    digest, prefix, count = hashlib.sha256(), hashlib.sha256(), 0
    with urllib.request.urlopen(request, timeout=90) as response:
        first = response.read(1)
        first_byte = time.monotonic() - started
        digest.update(first)
        prefix.update(first)
        count += len(first)
        expected = bounds[1] - bounds[0] + 1 if bounds else size
        if response.status != (206 if bounds else 200):
            raise ValueError("Unexpected HTTP status")
        if int(response.headers.get("Content-Length", -1)) != expected:
            raise ValueError("Image length differs from signed metadata")
        if bounds and response.headers.get("Content-Range") != f"bytes {bounds[0]}-{bounds[1]}/{size}":
            raise ValueError("Image range differs from request")
        while block := response.read(1024 * 1024):
            prefix.update(block[:max(0, (16 << 20) - count)])
            count += len(block)
            if count > expected:
                raise ValueError("Oversized image response")
            digest.update(block)
        if count != expected or sha256 and digest.hexdigest() != sha256:
            raise ValueError("Image body differs from signed metadata")
        duration = time.monotonic() - started
        return {"bytes": count, "sha256": digest.hexdigest(), "seconds": duration,
                "first_16mib_sha256": prefix.hexdigest(),
                "mib_per_second": count / (1024 ** 2) / duration, "first_byte_seconds": first_byte,
                "headers": {key: response.headers.get(key) for key in
                            ("ETag", "Content-Length", "Content-Range", "CF-Ray", "CF-Cache-Status", "Server-Timing")}}


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("Measurements run through public Actions")
    output = ROOT / "out/images-benchmark"
    output.mkdir(parents=True, exist_ok=True)
    baseline = origin("https://images.beamlineos.org")
    candidate = os.environ.get("BEAMLINE_IMAGES_CANDIDATE", "").strip()
    origins = [("baseline", baseline)] + ([("candidate", origin(candidate))] if candidate else [])
    report = {"source": os.environ["GITHUB_SHA"], "run": os.environ["GITHUB_RUN_ID"],
              "location": platform.node(), "system": platform.system(), "snapshot": SNAPSHOT, "measurements": []}
    reference = {}
    try:
        for label, host in origins:
            metadata = output / label
            metadata.mkdir()
            prefix = host + f"/snapshots/{SNAPSHOT}/aarch64/"
            for name in ("publication.json", "publication.json.gpg"):
                with urllib.request.urlopen(urllib.request.Request(prefix + name, headers={"User-Agent": USER_AGENT}), timeout=90) as response:
                    payload = response.read((256 << 10) + 1)
                if len(payload) > 256 << 10:
                    raise ValueError("Oversized publication")
                (metadata / name).write_bytes(payload)
            verify_manifest_signature(metadata)
            manifest = validate_manifest(json.loads((metadata / "publication.json").read_text()), SNAPSHOT)
            cases = [("deployed", {})] if label == "baseline" else [
                ("legacy-4-public", {"X-Beamline-Scheduling": "legacy", "X-Beamline-Prefetch": "4"}),
                *[(f"rolling-{n}-public", {"X-Beamline-Prefetch": str(n)}) for n in (4, 16, 32)],
            ]
            if label == "candidate" and os.environ.get("BENCHMARK_R2") == "true":
                cases.append(("rolling-16-r2", {"X-Beamline-Prefetch": "16", "X-Beamline-Transport": "r2"}))
            files = ["virt-aarch64.install.raw.zst", f"update/desktop-gnome_{SNAPSHOT}.sysext.raw",
                     f"update/posix-devel_{SNAPSHOT}.sysext.raw"]
            for case, headers in cases:
                for name in files:
                    file = manifest["artifacts"][name]
                    bounds = None if label == "baseline" and name.startswith("virt-") else (0, (16 << 20) - 1)
                    request_headers = dict(headers)
                    if bounds:
                        request_headers["Range"] = f"bytes={bounds[0]}-{bounds[1]}"
                    for repeat in range(3):
                        item = measure(prefix + name, request_headers, file["size"],
                                       file["sha256"] if bounds is None else None, bounds)
                        if item["headers"]["ETag"] != f'"sha256-{file["sha256"]}"':
                            raise ValueError("Image ETag differs from signed metadata")
                        identity = (name, bounds)
                        if identity in reference and reference[identity] != item["sha256"]:
                            raise ValueError("Benchmark cases returned different image bytes")
                        reference[identity] = item["sha256"]
                        if bounds is None:
                            reference[(name, (0, (16 << 20) - 1))] = item["first_16mib_sha256"]
                        item.update(origin=label, case=case, file=name, repeat=repeat + 1, range=bounds)
                        report["measurements"].append(item)
                        print(json.dumps(item), flush=True)
        report["passed"] = True
    except urllib.error.HTTPError as error:
        report["failure"] = {"url": error.url, "status": error.code,
                             "headers": dict(error.headers), "body": error.read(2048).decode(errors="replace")}
        raise
    finally:
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
