#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
                                                                              

import copy
import hashlib
import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
spec = importlib.util.spec_from_file_location("publish", ROOT / "tools/publish.py")
publish = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publish)


class Remote:
    def __init__(self):
        self.objects = {}
        self.events = []
        self.chunk_map = {}

    def get(self, key):
        return self.objects.get(key)

    def put(self, key, data):
        if key in self.objects:
            if self.objects[key] != data:
                raise ValueError("conflict")
            return False
        self.objects[key] = data
        self.events.append(key)
        return True

    def chunks(self):
        return dict(self.chunk_map)


class Publication(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.snapshot = "20261015.1247"
        self.prefix = f"snapshots/{self.snapshot}/aarch64/"
        digest = hashlib.sha256(b"payload").hexdigest()
        self.manifest = {"schema": 1, "snapshot": self.snapshot, "arch": "aarch64",
                         "chunking": {"desync_version": "1.1.4", "digest": "sha512-256", "sizes_kib": [16, 64, 256], "store": "store/"},
                         "installer_uncompressed_sha256": "a" * 64,
                         "metadata": {"update/SHA256SUMS": "b" * 64, "update/SHA256SUMS.gpg": "c" * 64},
                         "artifacts": {"virt-aarch64.install.raw.zst": {"sha256": digest, "size": 7,
                             "index": f"indexes/{digest}.caibx", "index_sha256": "d" * 64}}}
        (self.root / "indexes").mkdir()
        (self.root / "update").mkdir()
        (self.root / f"indexes/{digest}.caibx").write_bytes(b"index fixture")
        for name in ("SHA256SUMS", "SHA256SUMS.gpg"):
            (self.root / "update" / name).write_bytes(b"original signed channel metadata")
        (self.root / "publication.json").write_bytes(publish.canonical(self.manifest))
        (self.root / "publication.json.gpg").write_bytes(b"publication signature")
        self.remote = Remote()

    def replicate(self, existing):
        self.assertEqual(existing, self.remote.chunk_map)
        self.remote.events.append("replicate")
        self.remote.chunk_map["store/chunk"] = 123

    def verify(self):
        self.assertNotIn(self.prefix + "publication.json", self.remote.objects)
        self.remote.events.append("verify")
        return {"verified_artifacts": 1}

    def run_publish(self, verify=None):
        return publish.publish(self.root, self.manifest, self.remote, self.replicate, verify or self.verify)

    def test_commit_marker_is_last_and_follows_remote_verification(self):
        report = self.run_publish()
        self.assertEqual(self.remote.events[-2:], [self.prefix + "publication.json.gpg", self.prefix + "publication.json"])
        self.assertLess(self.remote.events.index("replicate"), self.remote.events.index("verify"))
        self.assertEqual(report["chunks_added"], 1)
        self.assertEqual(report["chunk_bytes_added"], 123)

    def test_repeat_is_idempotent(self):
        self.run_publish()
        before = dict(self.remote.objects)
        result = self.run_publish(verify=lambda: {"verified_artifacts": 1})
        self.assertEqual(result["chunks_added"], 0)
        self.assertEqual(result["metadata_uploaded"], 0)
        self.assertEqual(before, self.remote.objects)

    def test_conflicting_existing_index_or_manifest_stops_before_upload(self):
        for key in (next(iter(publish.package_files(self.root, self.manifest))), "publication.json"):
            self.remote = Remote()
            self.remote.objects[self.prefix + key] = b"conflict"
            with self.assertRaisesRegex(ValueError, "immutable object conflict"):
                self.run_publish()
            self.assertEqual(self.remote.events, [])

    def test_failed_verification_does_not_publish_a_commit_marker(self):
        def fail():
            raise ValueError("missing or corrupt chunk")
        with self.assertRaisesRegex(ValueError, "missing or corrupt"):
            self.run_publish(verify=fail)
        self.assertNotIn(self.prefix + "publication.json", self.remote.objects)
        self.assertNotIn(self.prefix + "publication.json.gpg", self.remote.objects)
                                                                              
        previous = dict(self.remote.objects)
        result = self.run_publish()
        self.assertTrue(all(self.remote.objects[k] == v for k, v in previous.items()))
        self.assertEqual(result["chunks_added"], 0)

    def test_incomplete_signature_can_resume_without_overwriting_data(self):
        signature = self.prefix + "publication.json.gpg"
        self.remote.objects[signature] = b"publication signature"
        self.run_publish()
        self.assertNotIn(signature, self.remote.events)
        self.assertEqual(self.remote.events[-1], self.prefix + "publication.json")

    def test_manifest_excludes_private_build_provenance(self):
        data = publish.canonical(self.manifest)
        self.assertNotIn(b"repository", data)
        self.assertNotIn(b"/Users/", data)
        self.assertEqual(publish.validate_manifest(self.manifest, self.snapshot), self.manifest)

    def test_unsafe_paths_and_unsupported_formats_are_refused(self):
        for path in ("../secret", "/tmp/secret", "indexes/../secret", "a\\b", "a//b"):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    publish.safe_path(path)
        for field, value in (("snapshot", "other"), ("arch", "x86_64"), ("schema", 2),
                             ("metadata", {}), ("metadata", []), ("artifacts", {}), ("artifacts", [])):
            bad = dict(self.manifest, **{field: value})
            with self.assertRaises(ValueError):
                publish.validate_manifest(bad, self.snapshot)
        for bad in ([], None, {**self.manifest, "artifacts": {"virt-aarch64.install.raw.zst": []}}):
            with self.assertRaises(ValueError):
                publish.validate_manifest(bad, self.snapshot)

    def test_index_cannot_escape_or_name_different_content(self):
        bad = copy.deepcopy(self.manifest)
        bad["artifacts"]["virt-aarch64.install.raw.zst"]["index"] = "../different"
        with self.assertRaises(ValueError):
            publish.validate_manifest(bad, self.snapshot)

    @unittest.skipUnless(shutil.which("gpg") and shutil.which("gpgv"), "GPG tools unavailable")
    def test_manifest_signature_is_valid_deterministic_and_detects_changes(self):
        signature = self.root / "publication.json.gpg"
        signature.unlink()
        publish.sign_manifest(self.root / "publication.json")
        first = signature.read_bytes()
        publish.verify_manifest_signature(self.root)
        signature.unlink()
        publish.sign_manifest(self.root / "publication.json")
        self.assertEqual(first, signature.read_bytes())
        (self.root / "publication.json").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "signature verification failed"):
            publish.verify_manifest_signature(self.root)


if __name__ == "__main__":
    unittest.main()
