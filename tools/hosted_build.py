#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys
import time

from hosted_experiment import ROOT, VERSIONS, run, serve_cache, write_json

TARGET = "base/beamline-shell.bst"
PREFIX = "build/"
ENVIRONMENT = ("R2_ACCOUNT_ID", "R2_BUCKET", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
               "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_SHA", "GITHUB_REPOSITORY",
               "GITHUB_ACTOR", "GITHUB_EVENT_NAME", "GITHUB_REF", "GITHUB_ACTIONS")


def identity():
    env = os.environ
    if (env.get("GITHUB_ACTIONS") != "true" or env.get("GITHUB_REPOSITORY") != "beamlineos/beamlineos"
            or env.get("GITHUB_ACTOR") != "c-lin-chunyi"
            or env.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
            or env.get("GITHUB_REF") != "refs/heads/main"):
        raise RuntimeError("Requires an owner-dispatched public main Actions run")
    value = env["GITHUB_RUN_ID"] + "-" + env["GITHUB_RUN_ATTEMPT"]
    if not re.fullmatch(r"\d+-\d+", value):
        raise RuntimeError("Invalid Actions identity")
    return value


def config(base, remote, cache=None):
    data = {"cachedir": str(cache or base / "cache"), "logdir": str(base / "logs"),
            "cache": {"quota": "16G", "cache-buildtrees": "never", "pull-buildtrees": False},
            "scheduler": {"network-retries": 1, "fetchers": 8, "pushers": 4, "builders": 1},
            "artifacts": {"override-project-caches": True, "servers": []},
            "source-caches": {"override-project-caches": True, "servers": []}}
    if cache is not None:
        data["cache"]["quota"] = "infinity"
    if remote:
        data["artifacts"]["servers"].append(
            {"url": "http://127.0.0.1:50051", "push": True, "type": "all"})
    path = base / ("remote.json" if remote else "local.json")
    write_json(path, data)
    return path


def bst(config_path, *args, **kwargs):
    return run(["bst", "--no-interactive", "--no-colors", "--config", config_path,
                "--directory", ROOT, "--option", "arch", "aarch64", *args], **kwargs)


def selection(config_path, deps):
    output = bst(config_path, "show", "--deps", deps, "--format", "%{name}|%{state}|%{full-key}",
                 TARGET, stdout=subprocess.PIPE, text=True).stdout
    rows = []
    for line in output.splitlines():
        name, state, key = line.split("|")
        if not re.fullmatch(r"[0-9a-f]{64}", key):
            raise RuntimeError("Incomplete source selection")
        rows.append({"element": name, "state": state, "key": key})
    return rows


def tree_manifest(directory):
    result = []
    for path in sorted(directory.rglob("*")):
        item = {"path": path.relative_to(directory).as_posix(),
                "mode": stat.S_IMODE(path.lstat().st_mode)}
        if path.is_symlink():
            item["link"] = os.readlink(path)
        elif path.is_file():
            with path.open("rb") as stream:
                item["sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
        elif path.is_dir():
            item["directory"] = True
        else:
            raise RuntimeError("Unexpected artifact file type")
        result.append(item)
    return result


def checkout(base, config_path):
    directory = base / "checkout"
    bst(config_path, "artifact", "checkout", "--deps", "none", "--no-integrate",
        "--directory", directory, TARGET)
    binary = directory / "usr/libexec/beamline-shell"
    header = binary.read_bytes()[:20]
    if header[:6] != b"\x7fELF\x02\x01" or int.from_bytes(header[18:20], "little") != 183:
        raise RuntimeError("Expected a native 64-bit little-endian AArch64 ELF")
    return {"files": tree_manifest(directory),
            "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(), "elf_machine": 183}


def compare(result, predecessor):
    if predecessor.get("target") != TARGET or predecessor.get("prefix") != PREFIX:
        raise RuntimeError("Unexpected target or cache namespace")
    if (predecessor.get("source") != os.environ["GITHUB_SHA"] or
            predecessor.get("run") != os.environ["GITHUB_RUN_ID"] or
            predecessor.get("attempt") != os.environ["GITHUB_RUN_ATTEMPT"]):
        raise RuntimeError("Evidence belongs to another source or run")
    if result["target_key"] != predecessor["target_key"]:
        raise RuntimeError("Artifact key differs between jobs")
    if result["artifact"] != predecessor["artifact"]:
        raise RuntimeError("Artifact bytes or file metadata differ between jobs")


def container_phase(phase):
    base = Path("/build-state")
    if (base / "cache").exists():
        raise RuntimeError("Hosted jobs must start with empty local caches")
    local, remote = config(base, False), config(base, True)
    run(["rpm", "-q", "buildstream", "buildbox", "buildstream-plugins"])
    write_json(base / "packages.json", sorted(run(["rpm", "-qa"], capture_output=True, text=True).stdout.splitlines()))
    before = selection(local, "none")[0]
    if before["state"] == "cached":
        raise RuntimeError("Target was already cached before the proof")
    result = {"phase": phase, "target": TARGET, "prefix": PREFIX, "target_key": before["key"],
              "cold_cache": True, "started": time.time(), "compiled": phase == "compile"}
    if phase == "compile":
        bst(remote, "artifact", "pull", "--deps", "build", TARGET)
        deps = selection(local, "build")
        if not deps or any(row["state"] != "cached" for row in deps):
            raise RuntimeError("Build dependencies were not restored completely from R2")
        result["dependencies"] = deps
        if selection(local, "none")[0]["state"] == "cached":
            raise RuntimeError("Dependency pull unexpectedly restored the target")
        result["compile_started"] = time.time()
        bst(local, "build", "--deps", "none", TARGET)
        result["compile_finished"] = time.time()
        result["artifact"] = checkout(base, local)
        bst(remote, "artifact", "push", "--deps", "none", TARGET)
    else:
        bst(remote, "artifact", "pull", "--deps", "none", TARGET)
        result["artifact"] = checkout(base, local)
    result["finished"] = time.time()
    write_json(base / "result.json", result)


def seed_vm():
                                                                          
    values = json.loads(sys.stdin.read())
    os.environ.update({key: values[key] for key in ENVIRONMENT})
    run_identity = identity()
    if platform.system() != "Linux" or platform.machine() != "aarch64":
        raise RuntimeError("Cache seed requires the existing native ARM Linux builder")
    base = Path.home() / ".cache/beamline/hosted-seed" / run_identity
    base.mkdir(parents=True, exist_ok=False)
    evidence = ROOT / "out/hosted-build/evidence"
    evidence.mkdir(parents=True)
    cachedir = Path.home() / ".cache/buildstream"
    local, remote = config(base, False, cachedir), config(base, True, cachedir)
    deps = selection(local, "build")
    if not deps or any(row["state"] != "cached" for row in deps):
        raise RuntimeError("Expected audited local build dependencies to be cached")
    if any(row["element"] == TARGET for row in deps):
        raise RuntimeError("Seed must exclude the target to force hosted compilation")
    target = selection(local, "none")[0]
    result = {"phase": "seed", "target": TARGET, "prefix": PREFIX,
              "target_key": target["key"], "dependencies": deps,
              "source": os.environ["GITHUB_SHA"], "run": os.environ["GITHUB_RUN_ID"],
              "attempt": os.environ["GITHUB_RUN_ATTEMPT"], "started": time.time(),
              "artifact": checkout(base, local)}
    write_json(evidence / "audit.json", result)
    try:
        with serve_cache(base, "aarch64", PREFIX, evidence, disk=True):
            bst(remote, "artifact", "push", "--deps", "build", TARGET)
        result.update(passed=True, finished=time.time())
        write_json(evidence / "result.json", result)
    finally:
        shutil.rmtree(base / "fast", ignore_errors=True)


def seed_local():
    run_identity = identity()
    if platform.system() != "Darwin":
        raise RuntimeError("Local cache seed runs on the registered Mac runner")
    source = Path(os.environ["BEAMLINE_SNAPSHOT_ROOT"]).resolve().parent / "hosted-build" / run_identity / "source"
    source.parent.mkdir(parents=True, exist_ok=False)
    run(["git", "clone", "--no-hardlinks", "--no-checkout", ROOT, source])
    run(["git", "-C", source, "checkout", "--detach", os.environ["GITHUB_SHA"]])
    try:
        run(["limactl", "shell", "--workdir", source, os.environ.get("LIMA_INSTANCE", "myos-builder"),
             "--", "python3", source / "tools/hosted_build.py", "seed-vm"],
            input=json.dumps({key: os.environ.get(key, "") for key in ENVIRONMENT}), text=True)
    finally:
        reports = source / "out/hosted-build/evidence"
        if reports.exists():
            shutil.copytree(reports, ROOT / "out/hosted-build/evidence", dirs_exist_ok=True)


def worker_dockerfile():
    return (
        f"FROM {VERSIONS['fedora']}\n"
        "RUN dnf install -y --setopt=install_weak_deps=False "
        f"buildstream-{VERSIONS['buildstream']} buildbox-{VERSIONS['buildbox']} "
        "buildstream-plugins-2.8.0 git-core lzip patch python3-dulwich "
        "python3-requests python3-tomlkit bubblewrap fuse3 "
        "&& dnf clean all\n")


def host(phase):
    identity()
    if platform.system() != "Linux" or platform.machine() != "aarch64":
        raise RuntimeError("Real build proof requires native hosted ARM Linux")
    commit = run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if commit != os.environ["GITHUB_SHA"]:
        raise RuntimeError("Checkout differs from the Actions source commit")
    run(["git", "diff", "--exit-code", "HEAD", "--"])
    base = ROOT / "out/hosted-build"
    base.mkdir(parents=True, exist_ok=False)
    evidence = base / "evidence"
    evidence.mkdir()
    dockerfile = base / "Dockerfile"
    dockerfile.write_text(worker_dockerfile())
    (base / ".dockerignore").write_text("*\n!Dockerfile\n")
    run(["docker", "build", "--tag", "beamline-hosted-build", "--file", dockerfile, base])
    container = base / "container"
    container.mkdir()
    with serve_cache(base, "aarch64", PREFIX, evidence, disk=True):
        with (evidence / "buildstream.log").open("w") as log:
            try:
                run(["docker", "run", "--rm", "--privileged", "--network", "host",
                     "--mount", f"type=bind,src={ROOT},dst=/work",
                     "--mount", f"type=bind,src={container},dst=/build-state",
                     "--workdir", "/work", "beamline-hosted-build", "python3",
                     "/work/tools/hosted_build.py", "container-" + phase],
                    stdout=log, stderr=subprocess.STDOUT)
            finally:
                print((evidence / "buildstream.log").read_text(), flush=True)
    run(["git", "diff", "--exit-code", "HEAD", "--"])
    result = json.loads((container / "result.json").read_text())
    result.update(source=os.environ["GITHUB_SHA"], run=os.environ["GITHUB_RUN_ID"],
                  attempt=os.environ["GITHUB_RUN_ATTEMPT"])
    result["passed"] = False
    write_json(evidence / "result.json", result)
    predecessor = ROOT / "out/hosted-build-input/result.json"
    if predecessor.exists():
        compare(result, json.loads(predecessor.read_text()))
        result["matches_predecessor"] = True
    elif phase == "recover":
        raise RuntimeError("Recovery requires the producer's small evidence report")
    result["passed"] = True
    write_json(evidence / "result.json", result)
    shutil.copyfile(container / "packages.json", evidence / "packages.json")


def main():
    parser = argparse.ArgumentParser(description="Seed, compile and recover one real Beamline artifact through R2.")
    parser.add_argument("phase", choices=("seed-local", "seed-vm", "compile", "recover",
                                          "container-compile", "container-recover"))
    phase = parser.parse_args().phase
    if phase == "seed-local":
        seed_local()
    elif phase == "seed-vm":
        seed_vm()
    elif phase.startswith("container-"):
        container_phase(phase.removeprefix("container-"))
    else:
        host(phase)


if __name__ == "__main__":
    main()
