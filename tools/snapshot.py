# SPDX-License-Identifier: MIT
                                                                           

import hashlib
import json
import re
import subprocess
import tempfile


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
