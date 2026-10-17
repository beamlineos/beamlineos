#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Upload-driven HTML discovery, immutable releases and concurrent refreshes."""
import copy
import hashlib
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import image_page
import publish


class Remote:
    def __init__(self):
        self.objects = {}
        self.writes = 0
        self.written_keys = []

    def get(self, key):
        return self.objects.get(key)

    def publications(self):
        return [key for key in self.objects if key.endswith("/publication.json")]

    def version(self, key):
        data = self.get(key)
        return data, hashlib.sha256(data).hexdigest() if data is not None else None

    def replace_page(self, key, data, etag):
        if self.version(key)[1] != etag:
            return False
        self.objects[key] = data
        self.writes += 1
        self.written_keys.append(key)
        return True


@unittest.skipUnless(shutil.which("gpg") and shutil.which("gpgv"), "GPG tools unavailable")
class Page(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.remote = Remote()

    def add_release(self, snapshot):
        digest = hashlib.sha256(b"fixture").hexdigest()
        artifact = {"sha256": digest, "size": 7, "index": f"indexes/{digest}.caibx", "index_sha256": "c" * 64}
        manifest = {"schema": 1, "snapshot": snapshot, "arch": "aarch64",
                    "chunking": {"desync_version": "1.1.4", "digest": "sha512-256", "sizes_kib": [16, 64, 256], "store": "store/"},
                    "installer_uncompressed_sha256": "a" * 64,
                    "artifacts": {"virt-aarch64.install.raw.zst": artifact,
                                  f"update/posix-devel_{snapshot}.sysext.raw": dict(artifact)},
                    "metadata": {"update/SHA256SUMS": "b" * 64, "update/SHA256SUMS.gpg": "d" * 64}}
        marker = self.root / "publication.json"
        marker.write_bytes(publish.canonical(manifest))
        marker.with_suffix(".json.gpg").unlink(missing_ok=True)
        publish.sign_manifest(marker)
        prefix = f"snapshots/{snapshot}/aarch64/"
        for name in ("publication.json", "publication.json.gpg"):
            self.remote.objects[prefix + name] = (self.root / name).read_bytes()
        return prefix, manifest

    def test_uploads_reconstruct_the_page_and_repeats_write_nothing(self):
        first, _ = self.add_release("20261015.1247")
        self.assertEqual(image_page.refresh(self.remote), {"snapshots": 1, "page_written": True})
        preserved = dict(self.remote.objects)
        second, _ = self.add_release("20261015.1248")
        self.assertEqual(image_page.refresh(self.remote), {"snapshots": 2, "page_written": True})
        page = self.remote.get(image_page.PAGE).decode()
        for prefix in (first, second):
            snapshot = prefix.split("/")[1]
            self.assertIn(f'href="/snapshots/{snapshot}/"', page)
            snapshot_page = self.remote.get(f"site/snapshots/{snapshot}/index.html").decode()
            self.assertIn(f'href="/{prefix}"', snapshot_page)
            architecture_page = self.remote.get("site/" + prefix + "index.html").decode()
            self.assertIn(f'href="/{prefix}virt-aarch64.install.raw.zst"', architecture_page)
            self.assertIn(f'href="/{prefix}update/"', architecture_page)
            self.assertNotIn("SHA256SUMS", architecture_page)
            update_page = self.remote.get("site/" + prefix + "update/index.html").decode()
            self.assertIn(f'href="/{prefix}update/SHA256SUMS"', update_page)
            self.assertIn(f'href="/{prefix}">../</a>', update_page)
        self.assertLess(page.index("20261015.1248"), page.index("20261015.1247"))
        self.assertNotIn("posix-devel", page)
        self.assertNotIn("<script", page)
        self.assertTrue(all(self.remote.get(key) == value for key, value in preserved.items() if key != image_page.PAGE))
        self.assertFalse(image_page.refresh(self.remote)["page_written"])
        self.assertEqual(self.remote.writes, 8)
        self.assertEqual(self.remote.written_keys[-1], image_page.PAGE)

    def test_root_lists_only_snapshots_and_all_pages_use_browser_defaults(self):
        root = (ROOT / "infra/images/public/index.html").read_text()
        self.assertEqual(root.count("<a "), 1)
        self.assertIn('href="/snapshots/">snapshots/</a>', root)
        _, manifest = self.add_release("20261015.1247")
        for page in [root, *(data.decode() for data in image_page.render([manifest]).values())]:
            self.assertNotIn("<style", page)
            self.assertNotIn('style=', page)
            self.assertNotIn('stylesheet', page)

    def test_refresh_re_lists_after_a_concurrent_publication(self):
        self.add_release("20261015.1247")
        original = self.remote.replace_page

        def race(key, data, etag):
            self.remote.replace_page = original
            self.add_release("20261015.1248")
            self.remote.objects[image_page.PAGE] = b"concurrent index"
            return False

        self.remote.replace_page = race
        self.assertEqual(image_page.refresh(self.remote)["snapshots"], 2)
        self.assertIn(b"20261015.1248", self.remote.get(image_page.PAGE))

    def test_incomplete_uploads_do_not_appear(self):
        self.remote.objects["snapshots/20261015.1247/aarch64/publication.json.gpg"] = b"not committed"
        self.assertEqual(image_page.refresh(self.remote)["snapshots"], 0)

    def test_invalid_signature_leaves_existing_page_untouched(self):
        prefix, _ = self.add_release("20261015.1247")
        image_page.refresh(self.remote)
        before = self.remote.get(image_page.PAGE)
        self.remote.objects[prefix + "publication.json"] += b"corrupt"
        with self.assertRaisesRegex(ValueError, "signature"):
            image_page.refresh(self.remote)
        self.assertEqual(before, self.remote.get(image_page.PAGE))

    def test_html_escapes_labels_and_quotes_urls(self):
        _, manifest = self.add_release("20261015.1247")
        manifest["artifacts"]["update/a<b&c.raw"] = copy.deepcopy(next(iter(manifest["artifacts"].values())))
        page = image_page.render([manifest])["site/snapshots/20261015.1247/aarch64/update/index.html"].decode()
        self.assertIn("a&lt;b&amp;c.raw", page)
        self.assertIn("a%3Cb%26c.raw", page)

    def test_page_only_mode_does_not_install_or_run_desync(self):
        self.add_release("20261015.1247")
        with patch.object(sys, "argv", ["publish", "--refresh-page", "--cache-root", str(self.root / "cache"),
                                       "--report", str(self.root / "report.json")]), \
                patch.object(publish, "R2", return_value=self.remote), patch.object(publish, "install") as install:
            self.assertEqual(publish.main(), 0)
        install.assert_not_called()


if __name__ == "__main__":
    unittest.main()
