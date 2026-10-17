#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
                                                                                 

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "20261015.1430"
SELECTIONS = ("project.refs", "junction.refs", "include/kernel/linux-commit.yml",
              "include/posix-devel/emacs-commit.yml")


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def copy_file(source, target):
                                                                                              
    result = subprocess.run(["cp", "-c", "-p", str(source), str(target)], capture_output=True)
    if result.returncode:
        shutil.copy2(source, target)
    return str(target)


def main():
    parser = argparse.ArgumentParser(description="Validate a trusted public commit in Actions.")
    parser.add_argument("mode", choices=("frozen", "head"))
    args = parser.parse_args()
    env = os.environ
    ref = env.get("GITHUB_REF", "")
    if (env.get("GITHUB_ACTIONS") != "true" or env.get("GITHUB_REPOSITORY") != "beamlineos/beamlineos"
            or env.get("GITHUB_ACTOR") != "c-lin-chunyi"
            or env.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
            or not (ref == "refs/heads/main" or ref.startswith("refs/heads/export/"))):
        parser.error("validation requires an owner-dispatched public branch Actions run")
    commit = git(ROOT, "rev-parse", "HEAD")
    if commit != env.get("GITHUB_SHA") or git(ROOT, "status", "--porcelain"):
        parser.error("checkout must be the clean, exact Actions commit")
    identity = f"{env['GITHUB_RUN_ID']}-{env['GITHUB_RUN_ATTEMPT']}"
    if not re.fullmatch(r"\d+-\d+", identity):
        parser.error("invalid Actions run identity")
    saved = Path(env["BEAMLINE_SNAPSHOT_ROOT"]).resolve()
    state = saved.parent / "validation" / identity
    state.mkdir(parents=True, exist_ok=False)
    source = state / "source"
    evidence = ROOT / "out/validation/evidence"
    evidence.mkdir(parents=True, exist_ok=False)
    report = {"schema": 1, "repository": env["GITHUB_REPOSITORY"], "commit": commit,
              "tree": git(ROOT, "rev-parse", "HEAD^{tree}"), "mode": args.mode,
              "run": env["GITHUB_RUN_ID"], "attempt": env["GITHUB_RUN_ATTEMPT"],
              "run_url": f"https://github.com/{env['GITHUB_REPOSITORY']}/actions/runs/{env['GITHUB_RUN_ID']}",
              "result": "failed", "baseline": BASELINE}
    status = 1
    try:
        subprocess.run(["git", "clone", "--no-hardlinks", "--no-checkout", str(ROOT), str(source)], check=True)
        subprocess.run(["git", "-C", str(source), "checkout", "--detach", commit], check=True)
        snapshots = source / "out/snapshots"
        snapshots.mkdir(parents=True)
        baseline = saved / BASELINE
        manifest = json.loads((baseline / "manifest.json").read_text())
        if manifest["snapshot"] != BASELINE or manifest["result"] != "green":
            raise ValueError("preserved baseline identity differs")
                                                                                           
        shutil.copytree(baseline, snapshots / BASELINE, copy_function=copy_file)
        (snapshots / "latest.json").write_text(json.dumps({"snapshot": BASELINE}) + "\n")
        command = [str(source / "ci/integrate"), "--no-commit",
                   "--frozen" if args.mode == "frozen" else "--force"]
        with (evidence / "integration.log").open("w") as log:
            process = subprocess.Popen(command, cwd=source, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True)
            for line in process.stdout:
                print(line, end="", flush=True)
                log.write(line)
                log.flush()
            status = process.wait()
        current = source / "out/integrations/current"
        latest = json.loads((snapshots / "latest.json").read_text())["snapshot"]
        if current.exists():
            candidate = current.read_text().strip()
            manifest_path = source / "out/integrations" / candidate / "manifest.json"
        elif latest != BASELINE:
            manifest_path = snapshots / latest / "manifest.json"
        else:
            candidates = sorted((source / "out/integrations").glob("*/manifest.json"))
            manifest_path = candidates[-1] if candidates else None
        if manifest_path and manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            shutil.copy2(manifest_path, evidence / "manifest.json")
            report["snapshot"] = manifest["snapshot"]
            report["sources"] = manifest["sources"]
            report["selinux"] = manifest.get("selinux")
            if manifest["result"] != "green" or manifest["repository"]["commit"] != commit:
                status = status or 1
        else:
            status = status or 1
        for path in SELECTIONS:
            dest = evidence / "selections" / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / path, dest)
        for path in (source / "out/aarch64/virt").glob("*.log"):
            shutil.copy2(path, evidence / path.name)
        report["result"] = "passed" if status == 0 else "failed"
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        report["error"] = str(exc)
        raise
    finally:
        (evidence / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2), flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
