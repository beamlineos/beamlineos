#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
import hashlib
import http.server
from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from benchmark_images import measure, origin


class BenchmarkTest(unittest.TestCase):
    def test_origins_are_explicit_https_and_have_no_credentials_or_paths(self):
        self.assertEqual(origin("https://images.example/"), "https://images.example")
        for value in ("http://images.example", "https://user:secret@images.example", "https://images.example/path",
                      "https://images.example/?key=value", "https://images.example/#fragment"):
            with self.assertRaises(ValueError):
                origin(value)

    def test_measurement_checks_status_lengths_ranges_and_hashes(self):
        payload = b"unchanged immutable image"
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                ranged = self.headers.get("Range") == "bytes=0-8"
                body = payload[:9] if ranged else payload
                self.send_response(206 if ranged else 200)
                self.send_header("Content-Length", str(len(body)))
                if ranged:
                    self.send_header("Content-Range", f"bytes 0-8/{len(payload)}")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/image"
            sha = hashlib.sha256(payload).hexdigest()
            report = measure(url, {}, len(payload), sha)
            self.assertEqual(report["sha256"], sha)
            self.assertGreater(report["mib_per_second"], 0)
            report = measure(url, {"Range": "bytes=0-8"}, len(payload), bounds=(0, 8))
            self.assertEqual(report["sha256"], hashlib.sha256(payload[:9]).hexdigest())
            for size, expected in ((len(payload) + 1, sha), (len(payload), "0" * 64)):
                with self.assertRaises(ValueError):
                    measure(url, {}, size, expected)
            with self.assertRaises(ValueError):
                measure(url, {}, len(payload), bounds=(0, 8))
        finally:
            server.shutdown()
            server.server_close()
            worker.join()


if __name__ == "__main__":
    unittest.main()
