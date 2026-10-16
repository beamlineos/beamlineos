#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Saved-artifact integrity and credential isolation for the manual P1 smoke job."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("p1_smoke", ROOT / "tools/p1-smoke.py")
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class SnapshotChecks(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.snapshot = smoke.SNAPSHOTS[0]
        self.channel = self.root / "update"
        self.channel.mkdir()
        self.raw_digest = hashlib.sha256(b"raw installer").hexdigest()
        self.compressed = "virt-aarch64.install.raw.zst"
        (self.root / self.compressed).write_bytes(b"compressed fixture")
        (self.channel / f"beamline_{self.snapshot}.efi").write_bytes(b"UKI fixture")
        self.write_sums(self.channel)
        (self.channel / "SHA256SUMS.gpg").write_bytes(b"signature fixture")
        self.manifest = {"snapshot": self.snapshot, "result": "green", "arch": ["aarch64"],
                         "artifacts": {"virt-aarch64.install.raw": {
                             "sha256": self.raw_digest, "zst": self.compressed,
                             "zst_sha256": smoke.sha256(self.root / self.compressed)}}}
        self.save_manifest()
        signature = patch.object(smoke, "verify_signature")
        signature.start()
        self.addCleanup(signature.stop)
        raw = patch.object(smoke, "raw_installer_hash", return_value=self.raw_digest)
        raw.start()
        self.addCleanup(raw.stop)

    def write_sums(self, directory):
        text = "".join(f"{smoke.sha256(p)} *{p.name}\n" for p in sorted(directory.iterdir())
                       if p.is_file() and p.name not in ("SHA256SUMS", "SHA256SUMS.gpg"))
        (directory / "SHA256SUMS").write_text(text)

    def save_manifest(self):
        (self.root / "manifest.json").write_text(json.dumps(self.manifest))
        self.write_sums(self.root)

    def verify(self):
        return smoke.verify_snapshot(self.root, self.snapshot, Path("unused keyring"))

    def test_valid_saved_snapshot(self):
        result = self.verify()
        self.assertEqual(result["snapshot"], self.snapshot)
        self.assertEqual(result["channel_files"], 1)
        self.assertEqual(result["installer_sha256"], self.raw_digest)

    def test_rejects_unsafe_duplicate_empty_and_malformed_checksums(self):
        checksum = "a" * 64
        for text in ("", "bad\n", f"{checksum} *../secret\n", f"{checksum} *a/b\n",
                     f"{checksum} *a\\b\n", f"{checksum} *a\n{checksum} *a\n"):
            with self.subTest(text=text):
                (self.root / "SHA256SUMS").write_text(text)
                with self.assertRaises(ValueError):
                    smoke.checksums(self.root / "SHA256SUMS")

    def test_corrupted_channel_artifact_is_refused(self):
        next(self.channel.glob("*.efi")).write_bytes(b"corruption")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.verify()

    def test_unlisted_and_mixed_version_artifacts_are_refused(self):
        extra = self.channel / "beamline_20990101.0000.efi"
        extra.write_bytes(b"wrong version")
        with self.assertRaisesRegex(ValueError, "unlisted"):
            self.verify()
        self.write_sums(self.channel)
        with self.assertRaisesRegex(ValueError, "mixes snapshot versions"):
            self.verify()

    def test_symlink_artifact_is_refused(self):
        artifact = next(self.channel.glob("*.efi"))
        outside = self.root / "outside"
        outside.write_bytes(artifact.read_bytes())
        artifact.unlink()
        artifact.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "non-regular"):
            self.verify()

    def test_wrong_manifest_identity_result_and_architecture_are_refused(self):
        for name, value in (("snapshot", "wrong"), ("result", "pending"), ("arch", ["x86_64"])):
            original = self.manifest[name]
            self.manifest[name] = value
            self.save_manifest()
            with self.assertRaisesRegex(ValueError, "identity, result or architecture"):
                self.verify()
            self.manifest[name] = original

    def test_uncompressed_installer_hash_is_verified(self):
        with patch.object(smoke, "raw_installer_hash", return_value="f" * 64):
            with self.assertRaisesRegex(ValueError, "uncompressed installer hash"):
                self.verify()

    def test_saved_installer_metadata_must_agree(self):
        self.manifest["artifacts"]["virt-aarch64.install.raw"]["zst_sha256"] = "f" * 64
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, "manifest and checksums disagree"):
            self.verify()

    @unittest.skipUnless(shutil.which("gpgv"), "gpgv not installed")
    def test_invalid_signature_is_refused_by_gpgv(self):
        # Bypass the fixture's signature mock to exercise the real verifier.
        original = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(original)
        with self.assertRaisesRegex(ValueError, "signature verification failed"):
            original.verify_signature(self.channel, ROOT / "files/keys/dev/update/import-pubring.pgp")


class R2Checks(unittest.TestCase):
    def test_invalid_configuration_is_refused_before_network_access(self):
        for account, bucket, url in (("bad", "bucket", "https://example.invalid"),
                                     ("a" * 32, "../bucket", "https://example.invalid"),
                                     ("a" * 32, "bucket", "http://example.invalid"),
                                     ("a" * 32, "bucket", "https://user:pass@example.invalid")):
            with self.subTest(account=account, bucket=bucket, url=url):
                with self.assertRaises(ValueError):
                    smoke.r2_round_trip(account, bucket, url)

    def test_missing_injected_credentials_cannot_fall_back_to_host_profiles(self):
        with patch.dict(os.environ, {"AWS_PROFILE": "owner-profile"}, clear=True):
            with self.assertRaisesRegex(ValueError, "missing AWS_ACCESS_KEY_ID"):
                smoke.r2_round_trip("a" * 32, "bucket", "https://example.invalid")

    def test_s3_and_public_reads_match_without_inheriting_owner_credentials(self):
        payloads = []
        def aws(command, **kwargs):
            env = kwargs["env"]
            self.assertNotIn("AWS_PROFILE", env)
            self.assertNotIn("AWS_SESSION_TOKEN", env)
            self.assertEqual(Path(env["AWS_CONFIG_FILE"]).read_bytes(), b"")
            self.assertEqual(env["AWS_ACCESS_KEY_ID"], "job-key")
            if "put-object" in command:
                payloads.append(Path(command[command.index("--body") + 1]).read_bytes())
                return subprocess.CompletedProcess(command, 0, b"{}", b"")
            if "head-object" in command:
                return subprocess.CompletedProcess(command, 0, json.dumps({"ContentLength": len(payloads[0])}).encode(), b"")
            Path(command[-1]).write_bytes(payloads[0])
            return subprocess.CompletedProcess(command, 0, b"{}", b"")
        class PublicResponse:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, _limit): return payloads[0]
        def public_read(request, **kwargs):
            self.assertEqual(request.get_header("User-agent"), "beamline-p1-smoke/1")
            return PublicResponse()
        with patch.dict(os.environ, {"AWS_ACCESS_KEY_ID": "job-key", "AWS_SECRET_ACCESS_KEY": "job-secret",
                                     "AWS_PROFILE": "owner-profile", "AWS_SESSION_TOKEN": "owner-token"}), \
                patch.object(smoke.subprocess, "run", side_effect=aws), \
                patch.object(smoke.urllib.request, "urlopen", side_effect=public_read):
            result = smoke.r2_round_trip("a" * 32, "bucket", "https://example.invalid")
            payloads.clear()
            progress = {}
            with patch.object(smoke.urllib.request, "urlopen", side_effect=smoke.urllib.error.HTTPError(
                    "https://example.invalid", 403, "Forbidden", None, None)):
                with self.assertRaisesRegex(ValueError, "public R2 read failed \\(HTTP 403\\)"):
                    smoke.r2_round_trip("a" * 32, "bucket", "https://example.invalid", progress)
            self.assertEqual(progress["s3_write"], "passed")
            self.assertEqual(progress["s3_read"], "passed")
            self.assertEqual(progress["public_read"], "pending")
            self.assertTrue(progress["key"].startswith("p1/smoke/"))
        self.assertEqual(result["public_read"], "passed")
        self.assertTrue(result["key"].startswith("p1/smoke/"))


if __name__ == "__main__":
    unittest.main()
