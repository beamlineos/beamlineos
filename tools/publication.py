# SPDX-License-Identifier: MIT
                                                                                        

import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile

from desync_tool import VERSION
import snapshot as checks

ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = "Beamline-CI/0.0 (+https://github.com/beamlineos/beamlineos)"
KEYRING = ROOT / "files/keys/dev/update/import-pubring.pgp"


def canonical(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def safe_path(value):
    if (not isinstance(value, str) or not value or "\\" in value or "\x00" in value
            or PurePosixPath(value).is_absolute() or any(p in ("", ".", "..") for p in value.split("/"))):
        raise ValueError("unsafe publication path")
    return value


def verify_manifest_signature(directory):
    with tempfile.TemporaryDirectory(prefix="beamline-publish-gpgv-") as home:
        result = subprocess.run(["gpgv", "--homedir", home, "--keyring", str(KEYRING),
                                 str(directory / "publication.json.gpg"), str(directory / "publication.json")],
                                capture_output=True)
        if result.returncode:
            raise ValueError("publication signature verification failed")


def validate_manifest(manifest, snapshot):
    if (not isinstance(manifest, dict) or manifest.get("schema") != 1 or manifest.get("snapshot") != snapshot or manifest.get("arch") != "aarch64"
            or manifest.get("chunking") != {"desync_version": VERSION, "digest": "sha512-256", "sizes_kib": [16, 64, 256], "store": "store/"}):
        raise ValueError("unsupported publication identity or format")
    if not isinstance(manifest.get("metadata"), dict) or set(manifest["metadata"]) != {"update/SHA256SUMS", "update/SHA256SUMS.gpg"}:
        raise ValueError("publication channel metadata is incomplete")
    if not isinstance(manifest.get("artifacts"), dict) or not manifest["artifacts"]:
        raise ValueError("publication has no artifacts")
    if "virt-aarch64.install.raw.zst" not in manifest["artifacts"]:
        raise ValueError("publication has no installer")
    if any(not re.fullmatch(r"[0-9a-f]{64}", str(value)) for value in manifest["metadata"].values()):
        raise ValueError("invalid channel metadata digest")
    if not re.fullmatch(r"[0-9a-f]{64}", str(manifest.get("installer_uncompressed_sha256", ""))):
        raise ValueError("invalid uncompressed installer digest")
    if snapshot == checks.SNAPSHOTS[1] and (manifest["installer_uncompressed_sha256"] != checks.BASELINE_RAW
            or manifest["metadata"]["update/SHA256SUMS"] != checks.BASELINE_CHANNEL):
        raise ValueError("P0 baseline identity changed")
    for name, artifact in manifest["artifacts"].items():
        safe_path(name)
        if not isinstance(artifact, dict):
            raise ValueError("invalid publication artifact")
        if name != "virt-aarch64.install.raw.zst" and not re.fullmatch(r"update/[^/]+", name):
            raise ValueError("unsupported publication artifact path")
        for field in ("sha256", "index_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}", str(artifact.get(field, ""))):
                raise ValueError("invalid publication digest")
        if artifact.get("index") != f"indexes/{artifact['sha256']}.caibx" or type(artifact.get("size")) is not int or artifact["size"] < 1:
            raise ValueError("invalid publication index or size")
    return manifest
