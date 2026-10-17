#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import hosted_build as build
from hosted_experiment import cache_config


class HostedBuildTest(unittest.TestCase):
    def test_compile_config_disables_remote_artifacts_and_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            config = json.loads(build.config(Path(temp), False).read_text())
            self.assertEqual(config["artifacts"], {"override-project-caches": True, "servers": []})
            self.assertEqual(config["source-caches"]["servers"], [])
            config = json.loads(build.config(Path(temp), True).read_text())
            self.assertEqual(len(config["artifacts"]["servers"]), 1)
            self.assertEqual(config["artifacts"]["servers"][0]["url"], "http://127.0.0.1:50051")

    def test_tree_comparison_detects_content_modes_and_symlink_targets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "binary"
            path.write_bytes(b"first")
            (root / "link").symlink_to("binary")
            first = build.tree_manifest(root)
            path.write_bytes(b"second")
            self.assertNotEqual(first, build.tree_manifest(root))
            path.write_bytes(b"first")
            path.chmod(0o755)
            self.assertNotEqual(first, build.tree_manifest(root))
            (root / "link").unlink()
            (root / "link").symlink_to("missing")
            self.assertEqual(build.tree_manifest(root)[1]["link"], "missing")

    def test_cross_job_comparison_requires_same_key_and_bytes(self):
        env = {"GITHUB_SHA": "abc", "GITHUB_RUN_ID": "1", "GITHUB_RUN_ATTEMPT": "1"}
        report = {"target": build.TARGET, "prefix": "build/", "source": "abc", "run": "1",
                  "attempt": "1", "target_key": "key", "artifact": {"files": []}}
        with patch.dict(os.environ, env):
            build.compare(report, report)
            for key in ("target_key", "artifact", "source"):
                changed = copy.deepcopy(report)
                changed[key] = "different"
                with self.assertRaises(RuntimeError):
                    build.compare(report, changed)

    def test_large_artifact_cache_uses_bounded_native_filesystem(self):
        config = cache_config("build/", Path("/native/cache"))
        store = config["stores"][0]["verify"]["backend"]["fast_slow"]
        self.assertEqual(store["fast"]["filesystem"]["eviction_policy"]["max_bytes"], "2gb")
        self.assertTrue(store["fast"]["filesystem"]["content_path"].startswith("/native/cache/"))
        self.assertEqual(store["slow"]["experimental_cloud_object_store"]["key_prefix"], "build/cas/")


if __name__ == "__main__":
    unittest.main()
