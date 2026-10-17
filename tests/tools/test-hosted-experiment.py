#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import hosted_experiment as experiment


class HostedExperimentTest(unittest.TestCase):
    def test_storage_boundary(self):
        prefix = experiment.prefix("123", "2", "aarch64")
        config = experiment.cache_config(prefix)
        cas, refs = config["stores"]
        self.assertTrue(cas["verify"]["verify_hash"])
        self.assertNotIn("verify", refs)
        for store, suffix in ((cas["verify"]["backend"], "cas/"), (refs, "refs/")):
            remote = store["fast_slow"]["slow"]["experimental_cloud_object_store"]
            self.assertEqual(remote["key_prefix"], prefix + suffix)
            self.assertEqual(remote["secret_access_key"], "${AWS_SECRET_ACCESS_KEY}")
        server = config["servers"][0]
        self.assertEqual(server["listener"]["http"]["socket_address"], "127.0.0.1:50051")
        self.assertFalse(set(server["services"]) & {"execution", "worker_api"})
        self.assertNotIn("schedulers", config)
        self.assertNotIn("workers", config)

    def test_reject_unscoped_or_unknown_storage(self):
        for args in (("../snapshots", "1", "aarch64"), ("12", "../", "aarch64"),
                     ("12", "1", "unknown")):
            with self.assertRaises(ValueError):
                experiment.prefix(*args)

    def test_log_redaction(self):
        env = {"AWS_ACCESS_KEY_ID": "key-value", "AWS_SECRET_ACCESS_KEY": "secret-value"}
        text = experiment.redact("failure key-value secret-value", env)
        self.assertEqual(text, "failure [REDACTED] [REDACTED]")
        self.assertNotIn("secret-value", json.dumps(experiment.cache_config("experiments/test/")))

    def test_requires_matching_cross_job_evidence_and_overlap(self):
        result = {"arch": "aarch64", "prefix": "experiments/hosted/1-1/aarch64/",
                  "run_id": "1", "attempt": "1", "source": "abc", "artifacts": []}
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for phase, writer, start, end in (("seed", "a", 0, 1),
                                               ("writer", "a", 2, 5), ("writer", "b", 3, 6)):
                path = directory / (phase + writer)
                path.mkdir()
                experiment.write_json(path / "result.json", {
                    **result, "phase": phase, "writer": writer, "passed": True,
                    "cold_cache": True, "writing_started": start, "writing_finished": end})
            experiment.compare_reports(result, directory)
            self.assertEqual(result["writer_overlap_seconds"], 2)
            path = directory / "writerb/result.json"
            report = json.loads(path.read_text())
            report["writing_started"] = 10
            experiment.write_json(path, report)
            with self.assertRaisesRegex(RuntimeError, "did not overlap"):
                experiment.compare_reports(result, directory)
            report["source"] = "another-source"
            experiment.write_json(path, report)
            with self.assertRaisesRegex(RuntimeError, "another source"):
                experiment.compare_reports(result, directory)


if __name__ == "__main__":
    unittest.main()
