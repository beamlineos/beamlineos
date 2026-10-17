#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import hosted_build as build
from hosted_experiment import cache_config


class HostedBuildTest(unittest.TestCase):
    def value(self):
        return {"mode": "full", "source": "a" * 40, "tree": "b" * 40, "run": "1", "attempt": "1",
                "snapshot": "20261018.0001", "arch": "aarch64", "prefix": build.PREFIX}

    def bundle(self, root):
        value = self.value()
        snapshot = value["snapshot"]
        names = ["install/install.raw", "firmware/provision.raw", "update/SHA256SUMS", "update/SHA256SUMS.gpg",
                 f"update/beamline_{snapshot}.efi", f"update/beamline-dev_{snapshot}.efi",
                 f"update/beamline_{snapshot}_{'a' * 32}.root.raw",
                 f"update/beamline_{snapshot}_{'b' * 32}.root-verity.raw"]
        names += [f"update/{ext}_{snapshot}.{kind}.raw" for ext in build.EXTENSIONS for kind in ("sysext", "confext")]
        files = {}
        for name in names:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(("payload:" + name).encode())
            files[name] = {"size": path.stat().st_size, "sha256": build.digest(path),
                           "part": build.image_part(name, snapshot)}
        build.write_json(root / "image-manifest.json", {"schema": 1, "identity": build.stamp(value), "files": files})
        return value

    def test_worker_output_is_live_and_retains_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            receipt, log = root / "receipt", root / "worker.log"

            class Console(io.StringIO):
                def flush(self):
                    if "worker is running\n" in self.getvalue() and log.exists():
                        if "worker is running\n" in log.read_text():
                            receipt.touch()
                    super().flush()

            child = (
                "import pathlib, sys, time; print('worker is running', flush=True); "
                f"receipt = pathlib.Path({str(receipt)!r}); deadline = time.monotonic() + 5\n"
                "while not receipt.exists() and time.monotonic() < deadline: time.sleep(0.01)\n"
                "print('worker stderr', file=sys.stderr, flush=True)\n"
                "sys.exit(7 if receipt.exists() else 9)\n")
            console = Console()
            with patch.object(sys, "stdout", console):
                with self.assertRaises(subprocess.CalledProcessError) as failure:
                    build.run_logged([sys.executable, "-u", "-c", child], log)
            self.assertEqual(failure.exception.returncode, 7)
            self.assertEqual(log.read_text(), "worker is running\nworker stderr\n")

    def test_offline_build_configuration_and_bounded_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            config = json.loads(build.config(Path(temp), False).read_text())
            self.assertEqual(config["artifacts"], {"override-project-caches": True, "servers": []})
            self.assertEqual(config["source-caches"]["servers"], [])
            self.assertEqual(config["scheduler"]["builders"], 1)
            self.assertEqual(config["cache"]["quota"], "60G")
            config = json.loads(build.config(Path(temp), True).read_text())
            self.assertEqual(config["artifacts"]["servers"][0]["url"], "http://127.0.0.1:50051")

    def test_frontier_uses_cached_outputs_without_uncached_bootstrap_history(self):
        def node(state="cached", runtime=(), build_deps=()):
            return {"key": "a" * 64, "state": state, "run": list(runtime), "build": list(build_deps)}
        nodes = {
            "image/install-virt.bst": node("waiting", build_deps=("desktop/gnome.bst", "compiler.bst")),
            "desktop/gnome.bst": node(runtime=("library.bst",)),
            "library.bst": node(build_deps=("uncached-bootstrap.bst",)),
            "compiler.bst": node(build_deps=("uncached-bootstrap.bst",)),
            "uncached-bootstrap.bst": node("fetch needed"),
        }
        with patch.object(build, "TARGETS", ["image/install-virt.bst"]):
            prerequisites = build.prerequisite_frontier(nodes, {"library.bst", "compiler.bst", "desktop/gnome.bst"})
        self.assertEqual(prerequisites, ["compiler.bst", "library.bst"])
        plan = build.group_plan(nodes, set(prerequisites), ["desktop/gnome.bst"])
        self.assertEqual(plan["inputs"], ["library.bst"])
        self.assertEqual(plan["outputs"], ["desktop/gnome.bst"])

    def test_graph_difference_keeps_first_divergent_inputs_and_both_graphs(self):
        def node(key, dependencies=()):
            return {"key": key, "build": list(dependencies), "run": []}
        expected = {"input": node("old"), "target": node("old-target", ["input"]), "removed": node("same")}
        actual = {"input": node("new"), "target": node("new-target", ["input"]), "added": node("new")}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaisesRegex(RuntimeError, "graph-difference.json"):
                build.check_keys(actual, expected, root)
            report = build.read(root / "graph-difference.json")
            self.assertEqual(report["first_divergent"], ["input"])
            self.assertEqual(report["changed"]["input"], {"expected": "old", "actual": "new"})
            self.assertEqual(report["missing"], ["removed"])
            self.assertEqual(report["added"], ["added"])
            self.assertEqual(build.read(root / "graph-actual.json"), actual)
            self.assertEqual(build.read(root / "graph-expected.json"), expected)
                                                                              
        self.assertTrue(build.graph_difference(actual, dict(actual, input=dict(actual["input"], state="cached")))["matches"])

    def test_context_rejects_old_schema_and_seed_records(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "context").mkdir()
            good = dict(self.value(), schema=2, baseline=build.BASELINE, prerequisites=[])
            env = {"GITHUB_SHA": good["source"], "GITHUB_RUN_ID": good["run"],
                   "GITHUB_RUN_ATTEMPT": good["attempt"], "BUILD_MODE": "full"}
            with patch.object(build, "paths", return_value=(None, None, root)), \
                    patch.object(build, "identity"), patch.object(build, "git", return_value=good["tree"]), \
                    patch.dict(os.environ, env):
                build.write_json(root / "context/context.json", good)
                self.assertEqual(build.context(), good)
                for bad in (dict(good, schema=1), dict(good, seed=[]), dict(good, mode="preflight")):
                    build.write_json(root / "context/context.json", bad)
                    with self.assertRaises(RuntimeError):
                        build.context()

    def test_failure_reporting_cannot_replace_the_original_error(self):
        original = RuntimeError("original container error")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(sys, "argv", ["build-hosted", "prepare"]), \
                    patch.object(build, "host", side_effect=original), \
                    patch.object(build, "paths", return_value=(root, root, root)), \
                    patch.object(build, "write_json", side_effect=PermissionError("unwritable report")):
                with self.assertRaises(RuntimeError) as caught:
                    build.main()
                self.assertIs(caught.exception, original)

    def test_artifact_recovery_rejects_key_and_tree_drift(self):
        report = [{"element": "target.bst", "key": "a", "files": {"hash": "b", "size": 1}}]
        build.compare_artifacts(report, report)
        for field, replacement in (("key", "different"), ("files", {"hash": "different", "size": 1})):
            changed = copy.deepcopy(report)
            changed[0][field] = replacement
            with self.assertRaises(RuntimeError):
                build.compare_artifacts(changed, report)

    def test_image_handoff_includes_installer_and_every_extension(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            value = self.bundle(root)
            result = build.verify_images(root, value)
            self.assertEqual({item["part"] for item in result["files"].values()},
                             {"installer", "system", *build.EXTENSIONS})
            for name in ("install/install.raw", f"update/posix-devel_{value['snapshot']}.sysext.raw"):
                path = root / name
                original = path.read_bytes()
                path.unlink()
                with self.assertRaises(RuntimeError):
                    build.verify_images(root, value)
                path.write_bytes(original + b"changed")
                with self.assertRaises(RuntimeError):
                    build.verify_images(root, value)
                path.write_bytes(original)

    def test_image_handoff_rejects_mixed_runs_extra_files_and_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            value = self.bundle(root)
            with self.assertRaises(RuntimeError):
                build.verify_images(root, dict(value, attempt="2"))
            (root / "extra").write_bytes(b"extra")
            with self.assertRaises(RuntimeError):
                build.verify_images(root, value)
            (root / "extra").unlink()
            path = root / "install/install.raw"
            saved = root / "same-bytes"
            saved.write_bytes(path.read_bytes())
            path.unlink()
            path.symlink_to(saved)
            saved.unlink()
            with self.assertRaises(RuntimeError):
                build.verify_images(root, value)

    def test_failed_missing_or_foreign_test_evidence_cannot_authorize_publication(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            value = self.value()
            path = root / "result.json"
            good = {"identity": build.stamp(value), "phase": "vm", "passed": True}
            build.write_json(path, good)
            self.assertEqual(build.checked_report(path, value, "vm"), good)
            for changed in (dict(good, passed=False), dict(good, phase="assemble"),
                            dict(good, identity=build.stamp(dict(value, run="2")))):
                build.write_json(path, changed)
                with self.assertRaises(RuntimeError):
                    build.checked_report(path, value, "vm")
            path.unlink()
            with self.assertRaises(FileNotFoundError):
                build.checked_report(path, value, "vm")

    def test_missing_logs_or_skipped_update_are_not_green(self):
        import integrate
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in integrate.TEST_EVIDENCE:
                (root / name).write_text("evidence\n")
            (root / "ci-test-update.log").write_text("passed\n")
            summary = {"policy_loaded": True, "mode": "enforcing", "unexpected_denials": 0}
            with patch.object(integrate, "selinux_summary", return_value=summary):
                self.assertEqual(build.require_vm_evidence(root, "snapshot"), summary)
                (root / "ci-test-update.log").write_text("SKIPPED\n")
                with self.assertRaises(RuntimeError):
                    build.require_vm_evidence(root, "snapshot")
                (root / "ci-test-update.log").write_text("passed\n")
                (root / integrate.TEST_LOGS[0]).unlink()
                with self.assertRaises(RuntimeError):
                    build.require_vm_evidence(root, "snapshot")

    def test_publisher_does_not_record_or_upload_after_failed_vm_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inputs = root / "out/hosted-build-input"
            images = inputs / "images"
            images.mkdir(parents=True)
            value = self.bundle(images)
            (inputs / "vm").mkdir()
            build.write_json(inputs / "vm/result.json", {"identity": build.stamp(value), "phase": "vm", "passed": False})
            with patch.object(build, "ROOT", root), patch.object(build, "context", return_value=value), \
                    patch.object(build, "apply_context"), patch.object(build, "run_logged") as command:
                with self.assertRaises(RuntimeError):
                    build.publish_images()
                command.assert_not_called()

    def test_workflow_keeps_tests_credential_free_and_publication_gated(self):
        from ruamel.yaml import YAML
        workflow = YAML(typ="safe").load((build.ROOT / ".github/workflows/build.yml").read_text())
        jobs = workflow["jobs"]
        self.assertNotIn("seed", jobs)
        self.assertNotIn("seed_local", workflow["on"]["workflow_dispatch"]["inputs"])
        self.assertEqual(jobs["prepare"]["runs-on"], "ubuntu-24.04-arm")
        self.assertNotIn("BEAMLINE_SNAPSHOT_ROOT", json.dumps(jobs["prepare"]))
        self.assertIn("inputs.mode == 'full'", jobs["assemble"]["if"])
        for name in ("workers", "assemble", "test", "publish"):
            self.assertIn("!cancelled()", jobs[name]["if"])
            self.assertIn("success", jobs[name]["if"])
        self.assertIn("needs.test.result == 'success'", jobs["publish"]["if"])
        self.assertIn("test", jobs["publish"]["needs"])
        self.assertNotIn("AWS_", json.dumps(jobs["test"]))
        self.assertEqual(set(jobs["workers"]["strategy"]["matrix"]["group"]), set(build.GROUPS))
        self.assertEqual(jobs["workers"]["runs-on"], "ubuntu-24.04-arm")

    def test_nativelink_fast_tier_is_native_and_bounded(self):
        config = cache_config("build/", Path("/native/cache"))
        store = config["stores"][0]["verify"]["backend"]["fast_slow"]
        self.assertEqual(store["fast"]["filesystem"]["eviction_policy"]["max_bytes"], "2gb")
        self.assertTrue(store["fast"]["filesystem"]["content_path"].startswith("/native/cache/"))
        self.assertEqual(store["slow"]["experimental_cloud_object_store"]["key_prefix"], "build/cas/")


if __name__ == "__main__":
    unittest.main()
