#!/usr/bin/env python3
# SPDX-License-Identifier: MIT

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal
import socket
import subprocess
import tarfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
VERSIONS = json.loads((ROOT / "infra/hosted/versions.json").read_text())
SIZE = 16 * 1024 * 1024
NAMES = ("seed", "shared", "writer-a", "writer-b")
HELP = "Bounded, cache-only NativeLink/R2 experiment on native hosted runners."


def run(args, **kwargs):
    print("+ " + " ".join(map(str, args)), flush=True)
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def prefix(run_id, attempt, arch):
    if not re.fullmatch(r"[0-9]+", run_id) or not re.fullmatch(r"[0-9]+", attempt):
        raise ValueError("Expected numeric Actions run identity")
    if arch not in VERSIONS["nativelink_sha256"]:
        raise ValueError("Unsupported native architecture")
    return f"experiments/hosted/{run_id}-{attempt}/{arch}/"


def cache_config(object_prefix):
    def store(suffix):
        return {"fast_slow": {
            "fast": {"memory": {"eviction_policy": {"max_bytes": "128mb"}}},
            "slow": {"experimental_cloud_object_store": {
                "provider": "r2", "account_id": "${R2_ACCOUNT_ID}",
                "bucket": "${R2_BUCKET}", "access_key_id": "${AWS_ACCESS_KEY_ID}",
                "secret_access_key": "${AWS_SECRET_ACCESS_KEY}",
                "key_prefix": object_prefix + suffix,
                "retry": {"max_retries": 3, "delay": 0.3, "jitter": 0.5},
            }},
        }}
    return {
        "stores": [
            {"name": "cas", "verify": {"verify_size": True, "verify_hash": True,
                                       "backend": store("cas/")}},
            {"name": "refs", **store("refs/")},
        ],
        "servers": [{"listener": {"http": {"socket_address": "127.0.0.1:50051"}},
                     "services": {"cas": [{"cas_store": "cas"}],
                                  "bytestream": {"cas_stores": {"": "cas"}},
                                  "capabilities": [{}], "fetch": [{"fetch_store": "refs"}],
                                  "push": [{"push_store": "refs"}]}}],
    }


def payload(name):
    if name not in NAMES:
        raise ValueError("Unknown fixture")
    return hashlib.shake_256(("beamline-cache-experiment-v1/" + name).encode()).digest(SIZE)


def make_project(base):
    project = base / "project"
    (project / "elements").mkdir(parents=True)
    (project / "project.conf").write_text(
        "name: beamline-cache-experiment\nmin-version: '2.8'\nelement-path: elements\n")
    for name in NAMES:
        data = project / "data" / name
        data.mkdir(parents=True)
        (data / "payload").write_bytes(payload(name))
        (project / "elements" / f"{name}.bst").write_text(
            f"kind: import\nsources:\n- kind: local\n  path: data/{name}\n")
    return project


def bst_config(base, remote):
    config = {"cachedir": str(base / "cache"), "logdir": str(base / "logs"),
              "cache": {"quota": "1G"}, "scheduler": {"network-retries": 1}}
    config["artifacts"] = {"override-project-caches": True, "servers": []}
    if remote:
        config["artifacts"]["servers"].append(
            {"url": "http://127.0.0.1:50051", "push": True, "type": "all"})
    path = base / ("remote.json" if remote else "local.json")
    write_json(path, config)
    return path


def cache_phase(phase, writer, base):
                                                                        
    if (base / "cache").exists():
        raise RuntimeError("Cold-cache proof requires a nonexistent BuildStream cache")
    project = make_project(base)
    local, remote = bst_config(base, False), bst_config(base, True)
    report = {"phase": phase, "writer": writer, "cold_cache": True,
              "versions": VERSIONS, "artifacts": [], "started": time.time()}
    run(["rpm", "-q", "buildstream", "buildbox"])

    def bst(config, *args, **kwargs):
        return run(["bst", "--no-interactive", "--no-colors", "--config", config,
                    "--directory", project, *args], **kwargs)

    def pull(name):
        bst(remote, "artifact", "pull", "--deps", "none", f"{name}.bst")

    def check(name):
        dest = base / "checkout" / name
        bst(local, "artifact", "checkout", "--deps", "none", "--no-integrate",
            "--directory", dest, f"{name}.bst")
        expected = hashlib.sha256(payload(name)).hexdigest()
        actual = hashlib.sha256((dest / "payload").read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f"Artifact payload mismatch: {name}")
        key = bst(local, "show", "--deps", "none", "--format", "%{full-key}",
                  f"{name}.bst", capture_output=True, text=True).stdout.strip()
        if not re.fullmatch(r"[0-9a-f]{64}", key):
            raise RuntimeError(f"Invalid artifact key: {key}")
        report["artifacts"].append({"name": name, "key": key, "sha256": actual, "bytes": SIZE})

    def push(name):
                                                                                          
        bst(local, "build", f"{name}.bst")
        check(name)
        bst(remote, "artifact", "push", "--deps", "none", f"{name}.bst")

    if phase == "seed":
        push("seed")
    elif phase == "writer":
        pull("seed")
        check("seed")
        report["writing_started"] = time.time()
        push("shared")
        push("writer-" + writer)
        report["writing_finished"] = time.time()
    else:
        for name in NAMES:
            pull(name)
            check(name)
    report["finished"] = time.time()
    report["passed"] = True
    write_json(base / "result.json", report)


def probe(base, arch):
    result = {"arch": arch, "cpu_count": os.cpu_count(),
              "meminfo": Path("/proc/meminfo").read_text().splitlines()[:3],
              "disk_available_bytes": os.statvfs(base).f_bavail * os.statvfs(base).f_frsize,
              "kvm_device": Path("/dev/kvm").exists(), "kvm_create_vm": False}
    try:
        with open("/dev/kvm", "rb+", buffering=0) as dev:
            result["kvm_api"] = fcntl.ioctl(dev, 0xAE00, 0)
            fd = fcntl.ioctl(dev, 0xAE01, 0)
            os.close(fd)
            result["kvm_create_vm"] = True
    except OSError as error:
        result["kvm_error"] = str(error)
    qemu = "qemu-system-" + ("x86_64" if arch == "x86_64" else "aarch64")
    result["qemu"] = run([qemu, "--version"], capture_output=True, text=True).stdout.splitlines()[0]
    for accel in ("kvm", "tcg"):
        machine = "q35" if arch == "x86_64" else "virt"
        cpu = "host" if accel == "kvm" else "max"
        with (base / f"qemu-{accel}.log").open("w+") as log:
            process = subprocess.Popen([qemu, "-machine", machine, "-accel", accel,
                                        "-cpu", cpu, "-m", "128M", "-S", "-display", "none",
                                        "-nodefaults", "-monitor", "none", "-serial", "none"],
                                       stdout=log, stderr=subprocess.STDOUT)
            try:
                process.wait(timeout=3)
                result[f"qemu_{accel}_started"] = False
            except subprocess.TimeoutExpired:
                result[f"qemu_{accel}_started"] = True
                process.terminate()
                process.wait(timeout=10)
    result["guest_boot_tested"] = False
    write_json(base / "capabilities.json", result)
    print(json.dumps(result, indent=2), flush=True)


def download_nativelink(base, arch):
    version = VERSIONS["nativelink"]
    archive = base / "nativelink.tar.gz"
    url = (f"https://github.com/TraceMachina/nativelink/releases/download/v{version}/"
           f"nativelink-{version}-{arch}-unknown-linux-musl.tar.gz")
    urllib.request.urlretrieve(url, archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != VERSIONS["nativelink_sha256"][arch]:
        raise RuntimeError("NativeLink archive checksum mismatch")
    binary = base / "nativelink"
    with tarfile.open(archive) as tar:
        members = [member for member in tar.getmembers()
                   if member.isfile() and Path(member.name).name == "nativelink"]
        if len(members) != 1:
            raise RuntimeError("Expected exactly one NativeLink binary")
        binary.write_bytes(tar.extractfile(members[0]).read())
    binary.chmod(0o755)
    return binary


def redact(text, environment):
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        value = environment.get(key)
        if value:
            text = text.replace(value, "[REDACTED]")
    return text


def compare_reports(result, directory):
    reports = [json.loads(path.read_text()) for path in sorted(directory.glob("*/result.json"))]
    if len(reports) != 3:
        raise RuntimeError("Verification requires seed and both writer reports")
    identity = ("arch", "prefix", "run_id", "attempt", "source")
    expected = {item["name"]: item for item in result["artifacts"]}
    for report in reports:
        if any(report[key] != result[key] for key in identity):
            raise RuntimeError("Evidence belongs to another source, run or architecture")
        if not report.get("passed") or not report.get("cold_cache"):
            raise RuntimeError("Missing successful cold-cache evidence")
        for item in report["artifacts"]:
            if expected.get(item["name"]) != item:
                raise RuntimeError("Artifact keys or payloads differ between independent jobs")
    writers = {report["writer"]: report for report in reports if report["phase"] == "writer"}
    if set(writers) != {"a", "b"} or sum(report["phase"] == "seed" for report in reports) != 1:
        raise RuntimeError("Missing independent producer/writers")
    overlap = (min(report["writing_finished"] for report in writers.values()) -
               max(report["writing_started"] for report in writers.values()))
    result["writer_overlap_seconds"] = overlap
    if overlap <= 0:
        raise RuntimeError("Writer jobs did not overlap; concurrent-writer proof is incomplete")


def host_phase(phase, writer):
    if platform.system() != "Linux" or os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("Run this experiment in public GitHub Actions on native Linux")
    arch = platform.machine()
    object_prefix = prefix(os.environ["GITHUB_RUN_ID"], os.environ["GITHUB_RUN_ATTEMPT"], arch)
    for name in ("R2_ACCOUNT_ID", "R2_BUCKET", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        if not os.environ.get(name):
            raise RuntimeError(f"Missing required experiment setting: {name}")
    base = ROOT / "out/hosted-experiment"
    base.mkdir(parents=True, exist_ok=False)
    evidence = base / "evidence"
    evidence.mkdir()
    run(["sudo", "apt-get", "update", "-qq"])
    package = "qemu-system-x86" if arch == "x86_64" else "qemu-system-arm"
    run(["sudo", "apt-get", "install", "-y", "--no-install-recommends", package, "acl"])
                                                                                       
    if Path("/dev/kvm").exists():
        run(["sudo", "setfacl", "-m", f"u:{os.getuid()}:rw", "/dev/kvm"])
    probe(evidence, arch)
    binary = download_nativelink(base, arch)
    config_path = base / "nativelink.json"
    write_json(config_path, cache_config(object_prefix))
    dockerfile = base / "Dockerfile"
    dockerfile.write_text(
        f"FROM {VERSIONS['fedora']}\n"
        "RUN dnf install -y --setopt=install_weak_deps=False "
        f"buildstream-{VERSIONS['buildstream']} buildbox-{VERSIONS['buildbox']} "
        "&& dnf clean all\n")
    (base / ".dockerignore").write_text("*\n!Dockerfile\n")
    run(["docker", "build", "--tag", "beamline-hosted-experiment", "--file", dockerfile, base])
    container = base / "container"
    container.mkdir()
    server_env = {key: value for key, value in os.environ.items() if key not in ("RUST_LOG", "RUST_BACKTRACE")}
    server_env["RUST_LOG"] = "warn"
    raw_log = base / "nativelink.log"
    with raw_log.open("w") as log:
        server = subprocess.Popen([binary, config_path], stdout=log, stderr=subprocess.STDOUT,
                                  env=server_env)
        try:
            deadline = time.monotonic() + 30
            while True:
                if server.poll() is not None:
                    raise RuntimeError("NativeLink exited before becoming ready")
                try:
                    with socket.create_connection(("127.0.0.1", 50051), timeout=1):
                        break
                except OSError:
                    if time.monotonic() > deadline:
                        raise RuntimeError("NativeLink startup timeout") from None
                    time.sleep(0.2)
            args = ["docker", "run", "--rm", "--network", "host",
                    "--mount", f"type=bind,src={ROOT},dst=/work,readonly",
                    "--mount", f"type=bind,src={container},dst=/experiment",
                    "--workdir", "/experiment", "beamline-hosted-experiment",
                    "python3", "/work/tools/hosted_experiment.py", "container", phase,
                    "--writer", writer]
                                                                                             
            with (evidence / "buildstream.log").open("w") as build_log:
                try:
                    run(args, stdout=build_log, stderr=subprocess.STDOUT)
                finally:
                    print((evidence / "buildstream.log").read_text(), flush=True)
            result = json.loads((container / "result.json").read_text())
            result.update({"arch": arch, "prefix": object_prefix,
                           "run_id": os.environ["GITHUB_RUN_ID"],
                           "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
                           "source": os.environ["GITHUB_SHA"]})
            if phase == "verify":
                compare_reports(result, ROOT / "out/hosted-inputs")
            write_json(evidence / "result.json", result)
        finally:
            if server.poll() is None:
                server.send_signal(signal.SIGTERM)
                try:
                    server.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()
            clean_log = redact(raw_log.read_text(), server_env)
            (evidence / "nativelink.log").write_text(clean_log)
            print(clean_log[-12000:], flush=True)


def main():
    parser = argparse.ArgumentParser(description=HELP)
    parser.add_argument("mode", choices=("host", "container"))
    parser.add_argument("phase", choices=("seed", "writer", "verify"))
    parser.add_argument("--writer", choices=("a", "b"), default="a")
    args = parser.parse_args()
    if args.mode == "host":
        host_phase(args.phase, args.writer)
    else:
        cache_phase(args.phase, args.writer, Path("/experiment"))


if __name__ == "__main__":
    main()
