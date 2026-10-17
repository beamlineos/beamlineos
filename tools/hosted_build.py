#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

from hosted_experiment import ROOT, VERSIONS, run, serve_cache, write_json

HELP = "Build, test and publish a frozen ARM image through Actions, NativeLink and R2."
PREFIX = "build/"
BASELINE = "20261015.1430"
GROUPS = {
    "base-posix": ["profiles/virt.bst", "posix/posix.bst", "posix-devel/posix-devel.bst"],
    "desktop": ["desktop/gnome.bst"],
    "printing-scanning": ["printing-scanning/printing-scanning.bst"],
    "installer": ["installer/installer.bst"],
}
TARGETS = ["image/install-virt.bst", "image/update-virt.bst",
           "image/firmware-provision-virt.bst", "tests/base-policy.bst"]
EXTENSIONS = ("posix", "posix-devel", "desktop-gnome", "printing-scanning")
STATE = ("project.refs", "junction.refs", "include/kernel/linux-commit.yml",
         "include/posix-devel/emacs-commit.yml", "include/snapshot.yml")
SAFE_ENV = ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_SHA", "GITHUB_REPOSITORY",
            "GITHUB_ACTOR", "GITHUB_EVENT_NAME", "GITHUB_REF", "GITHUB_ACTIONS", "BUILD_MODE")
SECRET_ENV = ("R2_ACCOUNT_ID", "R2_BUCKET", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")


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


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(path.read_text())


def git(*args):
    return run(["git", "-C", ROOT, *args], capture_output=True, text=True).stdout.strip()


def paths():
    base = ROOT / "out/hosted-build"
    return base, base / "evidence", ROOT / "out/hosted-build-input"


def context():
    value = read(paths()[2] / "context/context.json")
    identity()
    expected = {"source": os.environ["GITHUB_SHA"], "run": os.environ["GITHUB_RUN_ID"],
                "attempt": os.environ["GITHUB_RUN_ATTEMPT"], "arch": "aarch64", "prefix": PREFIX}
    if value.get("schema") != 2 or "seed" in value or any(value.get(k) != v for k, v in expected.items()):
        raise RuntimeError("Context belongs to another source, run or architecture")
    if value.get("mode") not in ("preflight", "full") or value["mode"] != os.environ.get("BUILD_MODE"):
        raise RuntimeError("Context belongs to another workflow mode")
    if not re.fullmatch(r"\d{8}\.\d{4}", value.get("snapshot", "")):
        raise RuntimeError("Invalid snapshot identity")
    if value.get("baseline") != BASELINE or value.get("tree") != git("rev-parse", "HEAD^{tree}"):
        raise RuntimeError("Context differs from checkout or baseline")
    return value


def stamp(value):
    return {k: value[k] for k in ("source", "tree", "run", "attempt", "snapshot", "arch", "prefix", "mode")}


def checked_report(path, value, phase):
    report = read(path)
    if report.get("identity") != stamp(value) or report.get("passed") is not True or report.get("phase") != phase:
        raise RuntimeError("Missing successful evidence for this source and run: " + str(path))
    return report


def clean_checkout():
    if git("rev-parse", "HEAD") != os.environ["GITHUB_SHA"]:
        raise RuntimeError("Checkout differs from Actions source")
    changed = git("diff", "--name-only", "HEAD", "--").splitlines()
    if set(changed) - set(STATE):
        raise RuntimeError("Tracked product files changed: " + ", ".join(changed))
    if git("ls-files", "--others", "--exclude-standard"):
        raise RuntimeError("Unexpected untracked source files")


def safe_relative(name):
    if not isinstance(name, str) or "\\" in name or "\0" in name or any(p in ("", ".", "..") for p in name.split("/")):
        raise RuntimeError("Unsafe handoff filename")
    path = Path(name)
    if path.is_absolute():
        raise RuntimeError("Absolute handoff filename")
    return path


def apply_context(value):
    clean_checkout()
    state = paths()[2] / "context/state"
    actual = {p.relative_to(state).as_posix() for p in state.rglob("*") if p.is_file()}
    if actual != set(value["state_files"]):
        raise RuntimeError("Incomplete integration state")
    allowed = set(STATE) | {"out/integrations/current", "out/snapshots/latest.json",
                           f"out/snapshots/{BASELINE}/manifest.json",
                           f"out/integrations/{value['snapshot']}/manifest.json"}
    allowed.update(f"out/integrations/{value['snapshot']}/before/{p}" for p in STATE)
    for name, expected in value["state_files"].items():
        path = safe_relative(name)
        source = state / path
        if name not in allowed or source.is_symlink() or digest(source) != expected:
            raise RuntimeError("Invalid integration state file: " + name)
        dest = ROOT / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
    clean_checkout()


def config(base, remote):
    data = {"cachedir": str(base / "cache"), "sourcedir": str(base / "sources"), "logdir": str(base / "logs"),
            "build": {"max-jobs": 8},
            "cache": {"quota": "60G", "cache-buildtrees": "never", "pull-buildtrees": False},
            "scheduler": {"network-retries": 1, "fetchers": 8, "pushers": 2, "builders": 1},
            "artifacts": {"override-project-caches": True, "servers": []},
            "source-caches": {"override-project-caches": True, "servers": []}}
    if remote:
        data["artifacts"]["servers"].append(
            {"url": "http://127.0.0.1:50051", "push": True, "type": "all"})
    path = base / ("remote.json" if remote else "local.json")
    write_json(path, data)
    return path


def bst(config_path, *args, **kwargs):
    return run(["bst", "--no-interactive", "--no-colors", "--strict", "--config", config_path,
                "--directory", ROOT, "--option", "arch", "aarch64", *args], **kwargs)


def graph(config_path, max_jobs=None):
    from ruamel.yaml import YAML
    from buildstream.element import _compose_artifact_name, _get_normal_name
    format_ = "RECORD %{name}|%{state}|%{full-key}\nBUILD\n%{build-deps}\nRUN\n%{runtime-deps}\nVARS\n%{vars}\nEND"
    options = ["--max-jobs", str(max_jobs)] if max_jobs is not None else []
    output = bst(config_path, *options, "show", "--deps", "all", "--format", format_, *TARGETS,
                 stdout=subprocess.PIPE, text=True).stdout
    result, yaml = {}, YAML(typ="safe")
    for block in output.split("RECORD ")[1:]:
        header, rest = block.split("\nBUILD\n", 1)
        build, rest = rest.split("\nRUN\n", 1)
        runtime, rest = rest.split("\nVARS\n", 1)
        variables, _ = rest.split("\nEND", 1)
        name, state, key = header.split("|")
        if not re.fullmatch(r"[0-9a-f]{64}", key):
            raise RuntimeError("Incomplete source selection: " + name)
        variables = yaml.load(variables)
        result[name] = {"key": key, "state": state,
                        "artifact": _compose_artifact_name(variables["project-name"], _get_normal_name(variables["element-name"]), key),
                        "build": yaml.load(build) or [],
                        "run": [n for n in (yaml.load(runtime) or []) if n != name]}
    if not set(TARGETS).issubset(result):
        raise RuntimeError("Incomplete image dependency graph")
    return result


def prerequisite_frontier(nodes, available):
    forced = {n for targets in GROUPS.values() for n in targets} | set(TARGETS)
    selected, seen = set(), set()
    def visit(name):
        if name in seen:
            return
        seen.add(name)
        row = nodes[name]
        for dep in row["run"]:
            visit(dep)
        if name in available and name not in forced and not name.startswith(("image/", "extensions/")):
            selected.add(name)
        else:
            for dep in row["build"]:
                visit(dep)
    for target in TARGETS:
        visit(target)
    return sorted(selected)


def group_plan(nodes, prerequisites, targets):
    inputs, outputs, seen = set(), [], set()
    def visit(name):
        if name in seen:
            return
        seen.add(name)
        row = nodes[name]
        for dep in row["run"]:
            visit(dep)
        if name in prerequisites:
            inputs.add(name)
            return
        for dep in row["build"]:
            visit(dep)
        outputs.append(name)
    for target in targets:
        visit(target)
    return {"inputs": sorted(inputs), "outputs": outputs, "targets": targets}


def artifact_record(name, key, payload):
    from buildstream._protos.buildstream.v2 import artifact_pb2
    value = artifact_pb2.Artifact.FromString(payload)
    if not value.build_success or value.strong_key != key or not value.files.hash:
        raise RuntimeError("Artifact does not match its successful strong key: " + name)
    return {"element": name, "key": key,
            "files": {"hash": value.files.hash, "size": value.files.size_bytes}}


def artifact_records(config_path, nodes, names):
    cache = Path(read(config_path)["cachedir"])
    refs = defaultdict(list)
    for path in (cache / "artifacts/refs").rglob("*"):
        if path.is_file():
            refs[path.name].append(path)
    records = []
    for name in names:
        key = nodes[name]["key"]
        candidates = sorted(refs[key])
        if not candidates:
            raise RuntimeError("Artifact is not cached: " + name)
        records.append(artifact_record(name, key, candidates[0].read_bytes()))
    return records


def remote_records(nodes):
                                                                                 
                                                                               
    import grpc
    from buildstream._artifactcache import REMOTE_ASSET_ARTIFACT_URN_TEMPLATE
    from buildstream._protos.build.bazel.remote.asset.v1 import remote_asset_pb2 as asset
    from buildstream._protos.build.bazel.remote.asset.v1 import remote_asset_pb2_grpc as asset_grpc
    from buildstream._protos.google.bytestream import bytestream_pb2 as stream
    from buildstream._protos.google.bytestream import bytestream_pb2_grpc as stream_grpc
    with grpc.insecure_channel("127.0.0.1:50051") as channel:
        fetch, blobs = asset_grpc.FetchStub(channel), stream_grpc.ByteStreamStub(channel)
        def load(item):
            name, node = item
            try:
                response = fetch.FetchBlob(asset.FetchBlobRequest(
                    uris=[REMOTE_ASSET_ARTIFACT_URN_TEMPLATE.format(node["artifact"])]), timeout=60)
            except grpc.RpcError as error:
                if error.code() == grpc.StatusCode.NOT_FOUND:
                    return None
                raise
            if response.status.code == 5:
                return None
            if response.status.code:
                raise RuntimeError("Remote metadata query failed: " + name)
            blob = response.blob_digest
            if not re.fullmatch(r"[0-9a-f]{64}", blob.hash) or not 0 < blob.size_bytes <= 1024 * 1024:
                raise RuntimeError("Invalid remote artifact metadata: " + name)
            resource = f"blobs/{blob.hash}/{blob.size_bytes}"
            data = bytearray()
            for part in blobs.Read(stream.ReadRequest(resource_name=resource), timeout=60):
                data.extend(part.data)
                if len(data) > blob.size_bytes:
                    raise RuntimeError("Oversized remote artifact metadata: " + name)
            if len(data) != blob.size_bytes or hashlib.sha256(data).hexdigest() != blob.hash:
                raise RuntimeError("Remote artifact metadata digest mismatch: " + name)
            return artifact_record(name, node["key"], data)
        with ThreadPoolExecutor(max_workers=8) as pool:
            return [row for row in pool.map(load, sorted(nodes.items())) if row is not None]


def compare_artifacts(actual, expected):
    def index(rows):
        result = {}
        for row in rows:
            if row["element"] in result and result[row["element"]] != row:
                raise RuntimeError("Producers disagree about an artifact tree")
            result[row["element"]] = row
        return result
    if index(actual) != index(expected):
        raise RuntimeError("Recovered artifact keys or file-tree digests differ from producer")


def pull(config_path, names):
    if names:
        bst(config_path, "artifact", "pull", "--deps", "none", *names)


def push(config_path, names):
    if names:
        bst(config_path, "artifact", "push", "--deps", "none", *names)


def graph_difference(actual, planned):
    added, missing = sorted(set(actual) - set(planned)), sorted(set(planned) - set(actual))
    changed = {name: {"expected": planned[name]["key"], "actual": actual[name]["key"]}
               for name in sorted(set(actual) & set(planned)) if actual[name]["key"] != planned[name]["key"]}
    roots = [name for name in changed if not any(
        dep in changed for dep in set(actual[name]["build"] + actual[name]["run"] +
                                     planned[name]["build"] + planned[name]["run"]))]
    return {"added": added, "missing": missing, "changed": changed, "first_divergent": roots,
            "matches": not (added or missing or changed)}


def check_keys(actual, planned, evidence=None):
    difference = graph_difference(actual, planned)
    if evidence is not None:
        try:
            write_json(evidence / "graph-actual.json", actual)
            write_json(evidence / "graph-expected.json", planned)
            write_json(evidence / "graph-difference.json", difference)
        except OSError as recording_error:
            if difference["matches"]:
                raise
            print("Could not record graph evidence: " + str(recording_error), file=sys.stderr, flush=True)
    if not difference["matches"]:
        print(json.dumps(difference, indent=2), flush=True)
        raise RuntimeError("Worker source graph differs from prepared keys; see graph-difference.json")


def save_context(value):
    context_dir = paths()[0] / "context"
    snapshot = value["snapshot"]
    state_files = list(STATE) + ["out/integrations/current", "out/snapshots/latest.json",
                               f"out/snapshots/{BASELINE}/manifest.json",
                               f"out/integrations/{snapshot}/manifest.json"]
    state_files += [f"out/integrations/{snapshot}/before/{p}" for p in STATE]
    value["state_files"] = {}
    for name in state_files:
        target = context_dir / "state" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
        value["state_files"][name] = digest(target)
    write_json(context_dir / "context.json", value)


def prepare():
    identity()
    native = Path("/build-state")
    local = config(native, False)
    config(native, True)
    previous = ROOT / "infra/hosted/baseline.json"
    baseline = read(previous)
    if baseline.get("snapshot") != BASELINE or baseline.get("result") != "green":
        raise RuntimeError("Invalid frozen baseline selection")
    dest = ROOT / "out/snapshots" / BASELINE
    dest.mkdir(parents=True)
    shutil.copyfile(previous, dest / "manifest.json")
    write_json(ROOT / "out/snapshots/latest.json", {"snapshot": BASELINE})
    env = dict(os.environ, BEAMLINE_BST_CONFIG=str(local))
    run_logged([sys.executable, "tools/integrate.py", "--arch", "aarch64", "resolve", "--frozen"],
               paths()[1] / "prepare.log", cwd=ROOT, env=env)
    nodes = graph(local)
    records = remote_records(nodes)
    available = {row["element"]: row for row in records}
    prerequisites = prerequisite_frontier(nodes, available)
    value = {"schema": 2, "source": os.environ["GITHUB_SHA"], "tree": git("rev-parse", "HEAD^{tree}"),
             "run": os.environ["GITHUB_RUN_ID"], "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
             "snapshot": (ROOT / "out/integrations/current").read_text().strip(),
             "mode": os.environ["BUILD_MODE"], "arch": "aarch64", "prefix": PREFIX, "baseline": BASELINE,
             "graph": nodes, "prerequisites": [available[name] for name in prerequisites],
             "groups": {name: group_plan(nodes, set(prerequisites), targets) for name, targets in GROUPS.items()}}
    save_context(value)
    write_json(paths()[1] / "graph-actual.json", nodes)
    write_json(paths()[1] / "result.json", {"phase": "prepare", "identity": stamp(value),
                                          "metadata_only": True, "prerequisites": len(prerequisites), "passed": True})
    clean_checkout()


def diagnose():
                                                                                
                                                                              
    reference = read(paths()[2] / "reference/context.json")
    if (reference.get("source") != "21421220aa713f0e0dfa22b4f662c075319e3217"
            or reference.get("snapshot") != "20261017.1441" or reference.get("run") != "39041828212"):
        raise RuntimeError("Unexpected failed-run reference")
    for name in STATE:
        source = paths()[2] / "reference/state" / name
        if digest(source) != reference["state_files"][name]:
            raise RuntimeError("Failed-run selection was altered")
        shutil.copyfile(source, ROOT / name)
    local = config(Path("/build-state"), False)
    actual = graph(local, max_jobs=4)
    difference = graph_difference(actual, reference["graph"])
    for name, data in (("graph-actual", actual), ("graph-expected", reference["graph"]), ("graph-difference", difference)):
        write_json(paths()[1] / (name + ".json"), data)
    first = difference["first_divergent"]
    if first:
        run_logged(["bst", "--no-colors", "--strict", "--config", local, "--option", "arch", "aarch64",
                    "--max-jobs", "4", "show", "--deps", "none", "--format", "%{name}\n%{vars}\n%{env}\n%{config}\n%{source-info}", *first],
                   paths()[1] / "first-divergent.log", cwd=ROOT)
    compatible = graph(local, max_jobs=8)
    write_json(paths()[1] / "graph-eight-jobs.json", compatible)
    compatibility = graph_difference(compatible, reference["graph"])
    write_json(paths()[1] / "graph-eight-jobs-difference.json", compatibility)
    print(json.dumps(difference, indent=2), flush=True)
    write_json(paths()[1] / "result.json", {"phase": "diagnose", "reference_run": reference["run"],
                                          "comparison_complete": True, "matches": difference["matches"],
                                          "matches_with_eight_jobs": compatibility["matches"]})
    clean_checkout()


def run_logged(args, path, cwd=None, env=None):
    command = list(map(str, args))
    print("+ " + " ".join(command), flush=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as log:
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, bufsize=1, cwd=cwd, env=env) as process:
            for line in process.stdout:
                log.write(line)
                log.flush()
                print(line, end="", flush=True)
            code = process.wait()
    if code:
        raise subprocess.CalledProcessError(code, command)


def worker_dockerfile(publisher=False):
    packages = ("python3 python3-ruamel-yaml git-core gnupg2 zstd awscli2 shadow-utils" if publisher else
                f"buildstream-{VERSIONS['buildstream']} buildbox-{VERSIONS['buildbox']} "
                "buildstream-plugins-2.8.0 git-core lzip patch python3-dulwich "
                "python3-requests python3-tomlkit bubblewrap fuse3 ShellCheck shadow-utils")
    return (f"FROM {VERSIONS['fedora']}\nRUN dnf install -y --setopt=install_weak_deps=False {packages} "
            "&& dnf clean all && git config --system --add safe.directory /work\n"
            "ARG BUILDER_UID\nARG BUILDER_GID\n"
            "RUN (getent group $BUILDER_GID || groupadd --gid $BUILDER_GID beamline) "
            "&& useradd --non-unique --uid $BUILDER_UID --gid $BUILDER_GID "
            "--home-dir /build-state/home --no-create-home beamline\n")


def sandbox_probe():
    evidence = paths()[1]
    evidence.mkdir(parents=True, exist_ok=True)
    before = {"uid": os.getuid(), "gid": os.getgid(), "netns": os.readlink("/proc/self/ns/net"),
              "apparmor": Path("/proc/self/attr/current").read_text().strip(),
              "status": [line for line in Path("/proc/self/status").read_text().splitlines()
                         if line.startswith(("Cap", "NoNewPrivs:", "Seccomp:"))]}
    write_json(evidence / "sandbox-host.json", before)
    home = Path(os.environ["HOME"])
    with tempfile.TemporaryFile(dir=home):
        pass
    script = ("import json,os; print(json.dumps({'uid':os.getuid(),'gid':os.getgid(),"
              "'netns':os.readlink('/proc/self/ns/net'),"
              "'devices':[s.split(':')[0].strip() for s in open('/proc/net/dev').readlines()[2:]]}))")
    result = run(["bwrap", "--unshare-all", "--die-with-parent", "--ro-bind", "/", "/",
                  "--dev-bind", "/dev", "/dev", "--proc", "/proc", "--uid", "0", "--gid", "0",
                  "--clearenv", "/usr/bin/python3", "-c", script], stdout=subprocess.PIPE, text=True)
    inside = json.loads(result.stdout)
    if inside["uid"] != 0 or inside["gid"] != 0 or inside["netns"] == before["netns"] or inside["devices"] != ["lo"]:
        raise RuntimeError("Build sandbox lacks isolated root/network namespaces")
    write_json(evidence / "sandbox.json", {"host": before, "sandbox": inside, "passed": True})


@contextmanager
def container_security(phase, evidence):
    enabled = Path("/sys/module/apparmor/parameters/enabled")
    if phase == "publish" or not enabled.exists() or enabled.read_text().strip() != "Y":
        yield []
        return
    profile = ROOT / "infra/hosted/apparmor.conf"
    restriction = Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns")
    write_json(evidence / "host-security.json", {
        "apparmor": True, "profile": "beamline-hosted-build",
        "restricted_userns": restriction.read_text().strip() if restriction.exists() else None})
    run(["sudo", "-n", "apparmor_parser", "-r", profile])
    try:
        yield ["--security-opt", "apparmor=beamline-hosted-build"]
    finally:
        original = sys.exception()
        try:
            run(["sudo", "-n", "apparmor_parser", "-R", profile])
        except (OSError, subprocess.SubprocessError) as error:
            if original is None:
                raise
            print("Could not unload build profile: " + str(error), file=sys.stderr, flush=True)


def worker(group):
    base, evidence, inputs = paths()
    value = context()
    apply_context(value)
    native = Path("/build-state")
    if (native / "cache").exists():
        raise RuntimeError("Hosted worker must start with an empty cache")
    local, remote = config(native, False), config(native, True)
    nodes = graph(local)
    check_keys(nodes, value["graph"], evidence)
    if value["mode"] == "preflight":
        write_json(evidence / "result.json", {"identity": stamp(value), "phase": group,
                                            "cold_cache": True, "keys_match": True, "passed": True,
                                            "payloads_pulled": False, "compiled": False})
        return
    plan = value["groups"][group] if group != "assemble" else {"targets": TARGETS}
    producer = []
    if group == "assemble":
        for name in GROUPS:
            report = checked_report(inputs / "workers" / ("build-worker-" + name) / "result.json", value, name)
            producer.extend(report["outputs"])
        selected = sorted({r["element"] for r in value["prerequisites"] + producer})
    else:
        selected = plan["inputs"]
    report = {"identity": stamp(value), "phase": group, "cold_cache": True,
              "started": time.time(), "passed": False}
    write_json(evidence / "result.json", report)
    report["pull_started"] = time.time()
    pull(remote, selected)
    recovered = artifact_records(local, nodes, selected)
    wanted = {r["element"]: r for r in value["prerequisites"] + producer}
    compare_artifacts(recovered, [wanted[n] for n in selected])
    refreshed = graph(local)
    if any(refreshed[name]["state"] == "cached" for name in plan["targets"]):
        raise RuntimeError("Worker target was restored instead of built")
    report.update(pull_finished=time.time(), inputs=recovered, build_started=time.time())
    write_json(evidence / "result.json", report)
    env = dict(os.environ, BEAMLINE_BST_CONFIG=str(local))
    if group == "assemble":
        for command in ("check", "test-base", "image"):
            run_logged([ROOT / "ci" / command], evidence / (command + ".log"), cwd=ROOT, env=env)
        report["outputs"] = artifact_records(local, nodes, TARGETS)
        report["image_manifest_sha256"] = digest(package_images(value))
    else:
        bst(local, "build", *plan["targets"])
        report["outputs"] = artifact_records(local, nodes, plan["outputs"])
    report["build_finished"] = time.time()
    if group != "assemble":
        push(remote, [r["element"] for r in report["outputs"]])
    import integrate
    report.update(passed=True, finished=time.time(), disk=shutil.disk_usage(native)._asdict(),
                  provenance=integrate.provenance())
    write_json(evidence / "packages.json", sorted(run(["rpm", "-qa"], capture_output=True, text=True).stdout.splitlines()))
    write_json(evidence / "result.json", report)
    clean_checkout()


def image_part(name, snapshot):
    if name == "install/install.raw":
        return "installer"
    if name == "firmware/provision.raw":
        return "system"
    for ext in EXTENSIONS:
        if name in (f"update/{ext}_{snapshot}.sysext.raw", f"update/{ext}_{snapshot}.confext.raw"):
            return ext
    if name in ("update/SHA256SUMS", "update/SHA256SUMS.gpg") or re.fullmatch(
            rf"update/beamline(?:-dev)?_{re.escape(snapshot)}(?:_[0-9a-f]{{32}}\.root(?:-verity)?\.raw|\.efi)", name):
        return "system"
    raise RuntimeError("Unexpected image payload: " + name)


def package_images(value):
    base, _, _ = paths()
    source = ROOT / "out/aarch64/virt"
    files = {}
    for directory in ("install", "update", "firmware"):
        for path in sorted((source / directory).rglob("*")):
            if not path.is_file():
                continue
            if path.is_symlink():
                raise RuntimeError("Image handoff must contain regular files")
            name = path.relative_to(source).as_posix()
            part = image_part(name, value["snapshot"])
            dest = base / "images" / part / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest)
            files[name] = {"size": path.stat().st_size, "sha256": digest(path), "part": part}
    manifest = base / "image-manifest.json"
    write_json(manifest, {"schema": 1, "identity": stamp(value), "files": files})
    validate_file_set(files, value["snapshot"])
    return manifest


def validate_file_set(files, snapshot):
    required = {"install/install.raw", "firmware/provision.raw", "update/SHA256SUMS", "update/SHA256SUMS.gpg",
                f"update/beamline_{snapshot}.efi", f"update/beamline-dev_{snapshot}.efi"}
    required.update(f"update/{name}_{snapshot}.{kind}.raw" for name in EXTENSIONS for kind in ("sysext", "confext"))
    if not required.issubset(files) or len(files) != len(required) + 2:
        raise RuntimeError("Incomplete installer, system or extension image handoff")
    for kind in ("root", "root-verity"):
        if sum(bool(re.fullmatch(rf"update/beamline_{re.escape(snapshot)}_[0-9a-f]{{32}}\.{kind}\.raw", n)) for n in files) != 1:
            raise RuntimeError("Incomplete SYSTEM/verity handoff")
    for name, item in files.items():
        safe_relative(name)
        if item.get("part") != image_part(name, snapshot) or not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", ""))) or type(item.get("size")) is not int or item["size"] < 1:
            raise RuntimeError("Invalid image manifest entry")


def verify_images(directory, value):
    manifest = read(directory / "image-manifest.json")
    if manifest.get("schema") != 1 or manifest.get("identity") != stamp(value):
        raise RuntimeError("Image handoff belongs to another source or run")
    files = manifest["files"]
    validate_file_set(files, value["snapshot"])
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()}
    if actual != set(files) | {"image-manifest.json"}:
        raise RuntimeError("Image handoff has missing or extra files")
    verify_payload(directory, manifest)
    return manifest


def verify_payload(directory, manifest):
    for name, item in manifest["files"].items():
        path = directory / safe_relative(name)
        if path.is_symlink() or path.stat().st_size != item["size"] or digest(path) != item["sha256"]:
            raise RuntimeError("Image handoff hash mismatch: " + name)


def copy_file(source, dest):
    if platform.system() == "Darwin":
        if subprocess.run(["cp", "-c", "-p", str(source), str(dest)], capture_output=True).returncode == 0:
            return str(dest)
    return shutil.copy2(source, dest)


def restore_images(value):
    base, _, inputs = paths()
    directory = inputs / "images"
    manifest = verify_images(directory, value)
    image = ROOT / "out/aarch64/virt"
    image.mkdir(parents=True, exist_ok=False)
    for name in manifest["files"]:
        dest = image / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        copy_file(directory / name, dest)
    (image / "extensions").mkdir()
    for kind in ("sysext", "confext"):
        shutil.copyfile(image / f"update/posix_{value['snapshot']}.{kind}.raw", image / f"extensions/posix.{kind}.raw")
    base.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(directory / "image-manifest.json", base / "image-manifest.json")
    return manifest


def clone(source):
    run(["git", "clone", "--no-hardlinks", "--no-checkout", ROOT, source])
    run(["git", "-C", source, "checkout", "--detach", os.environ["GITHUB_SHA"]])


def lima(source, phase, values):
    run(["limactl", "shell", "--workdir", source, os.environ.get("LIMA_INSTANCE", "myos-builder"),
         "--", "python3", "-u", source / "tools/hosted_build.py", phase], input=json.dumps(values), text=True)


def test_vm():
    value = context()
    saved = Path(os.environ["BEAMLINE_SNAPSHOT_ROOT"]).resolve()
    source = saved.parent / "hosted-build" / identity() / "vm-source"
    clone(source)
    shutil.copytree(paths()[2], source / "out/hosted-build-input", copy_function=copy_file)
    run_logged([sys.executable, source / "tools/hosted_build.py", "prepare-vm"], paths()[1] / "prepare.log")
    baseline = source / "out/snapshots" / BASELINE
    shutil.rmtree(baseline)
    shutil.copytree(saved / BASELINE, baseline, copy_function=copy_file)
    try:
        run_logged([source / "ci/test-vms"], paths()[1] / "vm-tests.log", cwd=source)
        lima(source, "evidence-vm", {key: os.environ.get(key, "") for key in SAFE_ENV})
    finally:
        evidence = source / "out/hosted-build/evidence"
        if evidence.exists():
            shutil.copytree(evidence, paths()[1], dirs_exist_ok=True)
        for path in (source / "out/aarch64/virt").glob("*.log"):
            shutil.copyfile(path, paths()[1] / path.name)
        screenshot = source / "out/aarch64/virt/desktop.ppm"
        if screenshot.exists():
            shutil.copyfile(screenshot, paths()[1] / screenshot.name)
    clean_checkout()


def require_vm_evidence(image, snapshot):
    import integrate
    for name in integrate.TEST_EVIDENCE:
        path = image / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError("Missing VM evidence: " + name)
    update = image / "ci-test-update.log"
    if not update.is_file() or "SKIPPED" in update.read_text():
        raise RuntimeError("Update coverage is absent or skipped")
    result = integrate.selinux_summary([image / n for n in integrate.TEST_LOGS], snapshot)
    if not result["policy_loaded"] or result["mode"] != "enforcing" or result["unexpected_denials"]:
        raise RuntimeError("VM security evidence is not green")
    return result


def evidence_vm():
    os.environ.update(json.loads(sys.stdin.read()))
    value = context()
    image = ROOT / "out/aarch64/virt"
    verify_payload(image, read(paths()[0] / "image-manifest.json"))
    result = {"identity": stamp(value), "phase": "vm", "passed": True,
              "image_manifest_sha256": digest(paths()[0] / "image-manifest.json"),
              "selinux": require_vm_evidence(image, value["snapshot"])}
    paths()[1].mkdir(parents=True, exist_ok=True)
    write_json(paths()[1] / "result.json", result)


def verify_worker_downloads(snapshot_root, snapshot, evidence):
    from publication import USER_AGENT, verify_manifest_signature, validate_manifest
    directory = evidence / "public"
    directory.mkdir()
    base = f"https://images.beamlineos.org/snapshots/{snapshot}/aarch64/"
    for name in ("publication.json", "publication.json.gpg"):
        with urllib.request.urlopen(urllib.request.Request(base + name, headers={"User-Agent": USER_AGENT}), timeout=120) as response:
            (directory / name).write_bytes(response.read())
    verify_manifest_signature(directory)
    manifest = validate_manifest(read(directory / "publication.json"), snapshot)
    expected = {"update/" + p.name: digest(p) for p in (snapshot_root / snapshot / "update").iterdir()}
    installer = "virt-aarch64.install.raw.zst"
    expected[installer] = digest(snapshot_root / snapshot / installer)
    declared = {name: item["sha256"] for name, item in manifest["artifacts"].items()} | manifest["metadata"]
    if declared != expected:
        raise RuntimeError("Public publication differs from tested snapshot files")
    reports = []
    for name, wanted in expected.items():
        print("Verifying Worker download: " + name, flush=True)
        size, prefix, hash_ = 0, b"", hashlib.sha256()
        with urllib.request.urlopen(urllib.request.Request(base + name, headers={"User-Agent": USER_AGENT}), timeout=120) as response:
            etag = response.headers.get("ETag")
            while block := response.read(1024 * 1024):
                hash_.update(block)
                size += len(block)
                if len(prefix) < 128:
                    prefix += block[:128 - len(prefix)]
        if hash_.hexdigest() != wanted or not etag:
            raise RuntimeError("Worker file digest or validator differs: " + name)
        with urllib.request.urlopen(urllib.request.Request(base + name, method="HEAD", headers={"User-Agent": USER_AGENT}), timeout=120) as response:
            if response.headers.get("ETag") != etag or int(response.headers["Content-Length"]) != size:
                raise RuntimeError("Worker HEAD differs: " + name)
        request = urllib.request.Request(base + name, headers={"User-Agent": USER_AGENT, "Range": f"bytes=0-{len(prefix)-1}"})
        with urllib.request.urlopen(request, timeout=120) as response:
            if response.status != 206 or response.read() != prefix or response.headers.get("ETag") != etag:
                raise RuntimeError("Worker Range differs: " + name)
        reports.append({"file": name, "sha256": wanted, "size": size, "etag": etag})
    write_json(evidence / "worker-downloads.json", reports)


def publish_images():
    value = context()
    if value["mode"] != "full":
        raise RuntimeError("Only a full build can publish")
    apply_context(value)
    manifest = restore_images(value)
    base, evidence, inputs = paths()
    report = checked_report(inputs / "vm/result.json", value, "vm")
    if report["image_manifest_sha256"] != digest(base / "image-manifest.json"):
        raise RuntimeError("VMs tested another image bundle")
    assembly = checked_report(inputs / "assemble/result.json", value, "assemble")
    if assembly["image_manifest_sha256"] != report["image_manifest_sha256"]:
        raise RuntimeError("Assembly and VM image handoffs differ")
    image = ROOT / "out/aarch64/virt"
    for path in (inputs / "vm").iterdir():
        if path.suffix == ".log" or path.name == "desktop.ppm":
            shutil.copyfile(path, image / path.name)
    security = require_vm_evidence(image, value["snapshot"])
    evidence.mkdir(parents=True, exist_ok=True)
    pending = ROOT / f"out/integrations/{value['snapshot']}/manifest.json"
    integration = read(pending)
    integration["provenance"] = assembly["provenance"]
    integration["infrastructure"] = {"identity": stamp(value), "assembly": assembly,
                                     "vm": report, "image_manifest_sha256": report["image_manifest_sha256"]}
    write_json(pending, integration)
    run_logged([sys.executable, "tools/integrate.py", "--arch", "aarch64", "record", "--result", "green", "--no-commit"],
               evidence / "record.log", cwd=ROOT)
    snapshots = ROOT / "out/snapshots"
    run_logged([ROOT / "ci/publish", value["snapshot"], "--snapshot-root", snapshots, "--repeat"],
               evidence / "publish.log", cwd=ROOT)
    verify_worker_downloads(snapshots, value["snapshot"], evidence)
    shutil.copyfile(snapshots / value["snapshot"] / "manifest.json", evidence / "manifest.json")
    shutil.copyfile(ROOT / "out/publish/report.json", evidence / "publication.json")
    write_json(evidence / "result.json", {"identity": stamp(value), "phase": "publish", "passed": True,
                                          "image_manifest_sha256": digest(base / "image-manifest.json"),
                                          "files": manifest["files"], "selinux": security,
                                          "url": f"https://images.beamlineos.org/snapshots/{value['snapshot']}/aarch64/"})
    clean_checkout()


def host(phase, group=None):
    identity()
    if platform.system() != "Linux" or platform.machine() != "aarch64":
        raise RuntimeError("Hosted image jobs require native ARM Linux")
    clean_checkout()
    base, evidence, _ = paths()
    base.mkdir(parents=True, exist_ok=False)
    evidence.mkdir()
    if phase != "publish" and shutil.disk_usage(base).free < 80 * 1024 ** 3:
        raise RuntimeError("Full-image worker requires 80 GiB free native disk")
    dockerfile = base / "Dockerfile"
    dockerfile.write_text(worker_dockerfile(phase == "publish"))
    (base / ".dockerignore").write_text("*\n!Dockerfile\n")
    run(["docker", "build", "--tag", "beamline-hosted-build", "--file", dockerfile,
         "--build-arg", f"BUILDER_UID={os.getuid()}", "--build-arg", f"BUILDER_GID={os.getgid()}", base])
    native = Path(tempfile.mkdtemp(prefix="beamline-hosted-", dir=os.environ.get("RUNNER_TEMP", "/tmp")))
    state, service = native / "state", native / "service"
    (state / "home").mkdir(parents=True)
    service.mkdir()
    write_json(evidence / "host.json", {"uid": os.getuid(), "gid": os.getgid(),
                                       "native_state": str(state), "source": str(ROOT)})
    command = ["docker", "run", "--rm", "--network", "host"]
    if phase != "publish":
        command.append("--privileged")
    for key in (*SAFE_ENV, *(SECRET_ENV if phase == "publish" else ())):
        command += ["--env", key]
    command += ["--user", f"{os.getuid()}:{os.getgid()}", "--env", "HOME=/build-state/home",
                "--mount", f"type=bind,src={ROOT},dst=/work", "--mount", f"type=bind,src={state},dst=/build-state",
                "--workdir", "/work", "beamline-hosted-build", "python3", "-u", "/work/tools/hosted_build.py",
                "container-" + phase]
    probe = command[:-1] + ["container-probe"]
    if phase == "prepare" and os.environ.get("BUILD_MODE") == "preflight":
        try:
            run_logged(probe, evidence / "sandbox-unprofiled.log")
            status = 0
        except subprocess.CalledProcessError as error:
            status = error.returncode
        write_json(evidence / "sandbox-unprofiled.json", {"exit_status": status})
        for name in ("sandbox-host.json", "sandbox.json", "container-failure.json"):
            path = evidence / name
            if path.exists():
                path.rename(evidence / ("unprofiled-" + name))
        kernel = subprocess.run(["sudo", "-n", "dmesg", "--color=never"], capture_output=True, text=True)
        (evidence / "sandbox-kernel.log").write_text("\n".join(
            line for line in kernel.stdout.splitlines() if 'apparmor="DENIED"' in line)[-24000:])
    with container_security(phase, evidence) as security:
        command[3:3] = security
        probe[3:3] = security
        if phase != "publish":
            run_logged(probe, evidence / "sandbox.log")
        if group:
            command += ["--group", group]
        if phase in ("publish", "diagnose"):
            run_logged(command, evidence / "worker.log")
        else:
            with serve_cache(service, "aarch64", PREFIX, evidence, disk=True):
                run_logged(command, evidence / "worker.log")
    clean_checkout()


def main():
    parser = argparse.ArgumentParser(description=HELP)
    parser.add_argument("phase", choices=("prepare", "diagnose", "worker", "assemble", "test", "publish",
                                          "container-prepare", "container-diagnose", "container-worker", "container-assemble",
                                          "container-publish", "container-probe", "prepare-vm", "evidence-vm"))
    parser.add_argument("--group", choices=GROUPS)
    args = parser.parse_args()
    try:
        if args.phase == "container-probe":
            sandbox_probe()
        elif args.phase == "container-prepare":
            prepare()
        elif args.phase == "container-diagnose":
            diagnose()
        elif args.phase == "container-worker":
            if args.group is None:
                parser.error("worker requires --group")
            worker(args.group)
        elif args.phase == "container-assemble":
            worker("assemble")
        elif args.phase == "container-publish":
            publish_images()
        elif args.phase == "test":
            test_vm()
        elif args.phase == "prepare-vm":
            value = context()
            apply_context(value)
            restore_images(value)
        elif args.phase == "evidence-vm":
            evidence_vm()
        else:
            if args.phase == "worker" and args.group is None:
                parser.error("worker requires --group")
            host(args.phase, args.group)
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        evidence = paths()[1]
        filename = "container-failure.json" if args.phase.startswith("container-") else "host-failure.json"
        try:
            evidence.mkdir(parents=True, exist_ok=True)
            write_json(evidence / filename, {"phase": args.phase, "group": args.group, "error": str(exc)})
        except OSError as recording_error:
            print("Could not record failure: " + str(recording_error), file=sys.stderr, flush=True)
        raise


def cli():
    try:
        main()
    except subprocess.CalledProcessError as error:
        print(str(error), file=sys.stderr, flush=True)
        raise SystemExit(error.returncode if error.returncode >= 0 else 128 - error.returncode) from None


if __name__ == "__main__":
    cli()
