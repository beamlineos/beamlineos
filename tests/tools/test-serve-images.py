#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Signed serving metadata and disposable-cache boundary regressions."""
import hashlib
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import serve_images as serving
import publish


class Cache(unittest.TestCase):
    def test_eviction_respects_watermarks_and_leaves_unrelated_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = Path(temporary)
            chunk = store / "aaaa" / ("a" * 64 + ".cacnk")
            chunk.parent.mkdir()
            chunk.write_bytes(b"12345678")
            other = store / "unrelated"
            other.write_bytes(b"leave this alone")
            working = chunk.parent / ".tmp-cacnk123"
            working.write_bytes(b"write in progress")
            link = chunk.parent / ("aaaa" + "b" * 60 + ".cacnk")
            link.symlink_to(other)
            external = store / "external"
            external.mkdir()
            foreign = external / ("c" * 64 + ".cacnk")
            foreign.write_bytes(b"outside the chunk store")
            (store / "cccc").symlink_to(external, target_is_directory=True)
            self.assertEqual(serving.evict_cache(store, 8), {"cache_bytes": 8, "evicted_chunks": 0})
            self.assertEqual(serving.evict_cache(store, 7), {"cache_bytes": 0, "evicted_chunks": 1})
            self.assertTrue(other.exists() and working.exists() and link.is_symlink() and foreign.exists())

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
            state = self.root / "state"
            state.mkdir()
            blobs, configuration = serving.prepare("https://store.example", [self.snapshot], state, "127.0.0.1:9080")
        self.assertEqual(len(blobs), 1)
        download = state / "site/snapshots" / self.snapshot / "aarch64/virt-aarch64.install.raw.zst"
        self.assertTrue(download.is_symlink())
        self.assertTrue(configuration.is_file())
        self.assertFalse((download.parent / "indexes").exists())

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
