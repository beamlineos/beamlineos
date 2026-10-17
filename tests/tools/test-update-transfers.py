#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The old client receives only existing resources; the candidate gets its complete set."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from update_transfers import channel_url, render


class Transfers(unittest.TestCase):
    def test_predecessor_filtering_preserves_complete_candidate_and_credential_escaping(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, old = root / "definitions", root / "old"
            source.mkdir()
            old.mkdir()
            body = '# prose\n[Source]\nPath=https://example.invalid/\nMatchPattern=posix_@v.raw\n[Target]\nPath=/var/lib/%A\\test\n'
            (source / "71-posix-sysext.transfer").write_text(body)
            (source / "72-new-sysext.transfer").write_text(body)
            (source / "10-system.transfer").write_text(body)
            (old / "posix_20261015.1430.sysext.raw").touch()
            candidate = render(source, "http://10.0.2.2:1234/")
            predecessor = render(source, "http://10.0.2.2:1234/", old)
            self.assertIn("72-new-sysext.transfer", candidate)
            self.assertNotIn("72-new-sysext.transfer", predecessor)
            self.assertIn("71-posix-sysext.transfer", predecessor)
            self.assertIn("10-system.transfer", predecessor)
            self.assertNotIn("# prose", candidate)
            self.assertNotIn("https://example.invalid/", candidate)
            self.assertIn("Path=http://10.0.2.2:1234/\\n", candidate)
            self.assertIn("Path=/var/lib/%%A\\\\test\\n", candidate)

    def test_url_validation_retains_http_fixture_support_and_rejects_ambiguous_inputs(self):
        self.assertEqual(channel_url("https://images.example/update"), "https://images.example/update/")
        self.assertEqual(channel_url("http://10.0.2.2:1234/"), "http://10.0.2.2:1234/")
        for value in ("file:///tmp/a", "https://a:b@example/", "https://example/?x", "https://example/#x", "https://example/ a"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                channel_url(value)


if __name__ == "__main__":
    unittest.main()
