#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Static checks and isolated regression-test discovery."""

import os
from pathlib import Path
import subprocess
import sys

from ruamel.yaml import YAML

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    print("==> " + " ".join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), cwd=ROOT, check=True)


def main():
    os.chdir(ROOT)
    # Each test gets a fresh interpreter; a test cannot poison another's imports or mocks.
    os.environ["PYTHONPATH"] = str(ROOT / "tools") + os.pathsep + os.environ.get("PYTHONPATH", "")
    run(sys.executable, "tools/check-policy.py", "--units", "files", "--allowlist", "policy/unit-shell-allowlist.txt",
        "--selinux-policy", "files/selinux/policy", "--extensions-policy", "files/base")
    for path in sorted(Path("tools").glob("*.py")):
        compile(path.read_text(), str(path), "exec")
    for path in sorted(Path("tests/tools").glob("test-*.py")):
        run(sys.executable, path)
    run(sys.executable, "tools/integrate.py", "check-lockfiles")
    paths = {Path("project.conf"), Path("project.refs"), Path("junction.refs")}
    for directory, pattern in (("include", "*.yml"), ("elements", "*.bst"),
                               ("lima", "*.yaml"), (".github/workflows", "*.yml")):
        paths.update(Path(directory).rglob(pattern))
    for path in sorted(paths):
        YAML(typ="safe").load(path.read_text())
    print(f"==> YAML: {len(paths)} files parsed", flush=True)
    scripts = [path for path in sorted(Path("ci").iterdir()) if path.is_file()
               and (path.read_bytes().startswith(b"#!/bin/sh") or b"# shellcheck shell=sh" in path.read_bytes())]
    run("shellcheck", "--external-sources", *scripts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
