#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Signed metadata and complete native-service deployment bundle regressions."""
import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import prepare_images as serving
import publish


class LocalMetadata(unittest.TestCase):
    def test_local_metadata_cannot_be_replaced_or_follow_a_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "metadata"
            serving.keep_file(path, b"original")
            serving.keep_file(path, b"original")
            with self.assertRaises(ValueError):
                serving.keep_file(path, b"changed")
            link = path.with_suffix(".link")
            link.symlink_to(path)
            with self.assertRaises(ValueError):
                serving.keep_file(link, b"original")
            self.assertEqual(path.read_bytes(), b"original")


@unittest.skipUnless(shutil.which("gpg") and shutil.which("gpgv"), "GPG tools unavailable")
class Metadata(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.snapshot = "20261015.1247"
        digest = hashlib.sha256(b"fixture blob").hexdigest()
        index = f"indexes/{digest}.caibx"
        artifact = {"sha256": digest, "size": 12, "index": index,
                    "index_sha256": hashlib.sha256(b"fixture index").hexdigest()}
        channel = self.root / "SHA256SUMS"
        channel.write_text(f"{digest}  beamline_{self.snapshot}.efi\n")
        publish.sign_manifest(channel)
        self.objects = {index: b"fixture index", "update/SHA256SUMS": channel.read_bytes(),
                        "update/SHA256SUMS.gpg": channel.with_suffix(".gpg").read_bytes()}
        self.manifest = {"schema": 1, "snapshot": self.snapshot, "arch": "aarch64",
                         "chunking": {"desync_version": "1.1.4", "digest": "sha512-256", "sizes_kib": [16, 64, 256], "store": "store/"},
                         "installer_uncompressed_sha256": "a" * 64,
                         "artifacts": {"virt-aarch64.install.raw.zst": artifact,
                                       f"update/beamline_{self.snapshot}.efi": dict(artifact)},
                         "metadata": {name: hashlib.sha256(data).hexdigest() for name, data in self.objects.items()
                                      if name.startswith("update/")}}
        self.sign()

    def sign(self):
        path = self.root / "publication.json"
        path.write_bytes(publish.canonical(self.manifest))
        path.with_suffix(".json.gpg").unlink(missing_ok=True)
        publish.sign_manifest(path)
        self.objects.update({"publication.json": path.read_bytes(),
                             "publication.json.gpg": path.with_suffix(".json.gpg").read_bytes()})

    def get(self, base, key):
        return self.objects[key.removeprefix(f"snapshots/{self.snapshot}/aarch64/")]

    def test_signed_metadata_and_aliases_prepare_one_shared_mount(self):
        with patch.object(serving, "public_get", self.get):
            bundle = self.root / "bundle"
            count = serving.prepare("https://store.example", [self.snapshot], bundle)
        self.assertEqual(count, 1)
        download = bundle / "data/site/snapshots" / self.snapshot / "aarch64/virt-aarch64.install.raw.zst"
        self.assertTrue(download.is_symlink())
        self.assertFalse((download.parent / "indexes").exists())
        self.assertTrue((bundle / "data/Caddyfile").is_file())
        self.assertEqual(len(list((bundle / "data/images").glob("*.env"))), 1)
        self.assertTrue((bundle / "systemd/beamline-images.target.d/snapshots.conf").is_file())

    def test_late_failure_does_not_leave_a_deployable_partial_bundle(self):
        def late_failure(base, key):
            if self.snapshot not in key:
                raise ValueError("missing second release")
            return self.get(base, key)
        bundle = self.root / "bundle"
        with patch.object(serving, "public_get", late_failure), self.assertRaisesRegex(ValueError, "second release"):
            serving.prepare("https://store.example", [self.snapshot, "20261015.1430"], bundle)
        self.assertFalse(bundle.exists())

    def test_preparation_does_not_replace_an_existing_deployment_bundle(self):
        bundle = self.root / "bundle"
        bundle.mkdir()
        (bundle / "leave-me").write_text("existing configuration")
        with self.assertRaisesRegex(ValueError, "already exists"):
            serving.prepare("https://store.example", [self.snapshot], bundle)
        self.assertEqual((bundle / "leave-me").read_text(), "existing configuration")

    def test_private_host_umask_still_produces_a_readable_deployment(self):
        bundle = self.root / "bundle"
        previous = os.umask(0o077)
        try:
            with patch.object(serving, "public_get", self.get):
                serving.prepare("https://store.example", [self.snapshot], bundle)
        finally:
            os.umask(previous)
        self.assertEqual((bundle / "data/site").stat().st_mode & 0o777, 0o755)
        self.assertEqual((bundle / "data/Caddyfile").stat().st_mode & 0o777, 0o644)
        self.assertEqual((bundle / "libexec/beamline-image-ready").stat().st_mode & 0o777, 0o755)

    def test_signature_failure_leaves_no_accepted_local_release(self):
        self.objects["publication.json"] += b"changed"
        destination = self.root / "accepted"
        with patch.object(serving, "public_get", self.get), self.assertRaisesRegex(ValueError, "signature"):
            serving.fetch_release("https://store.example", self.snapshot, destination)
        self.assertFalse(destination.exists())

    def test_corrupted_index_is_refused_before_accepting_local_release(self):
        index = self.manifest["artifacts"]["virt-aarch64.install.raw.zst"]["index"]
        self.objects[index] = b"wrong index"
        destination = self.root / "accepted"
        with patch.object(serving, "public_get", self.get), self.assertRaisesRegex(ValueError, "digest mismatch"):
            serving.fetch_release("https://store.example", self.snapshot, destination)
        self.assertFalse(destination.exists())

    def test_signed_manifest_must_agree_with_original_signed_channel(self):
        self.manifest["artifacts"].pop(f"update/beamline_{self.snapshot}.efi")
        self.sign()
        with patch.object(serving, "public_get", self.get), self.assertRaisesRegex(ValueError, "signed channel"):
            serving.fetch_release("https://store.example", self.snapshot, self.root / "accepted")


if __name__ == "__main__":
    unittest.main()
