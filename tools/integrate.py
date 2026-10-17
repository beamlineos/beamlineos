#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
HELP = """Integration cycles (docs/spec.md §17, §31).

  resolve [--force | --frozen]               pin every tracked component to an exact commit
  record --result green|failed|aborted [--no-commit]
                                             publish the snapshot or record the failure

`resolve` reads policy/tracking.toml and writes the resolved refs into project.refs and
junction.refs (and, for Linux, the selected commit into include/kernel/linux-commit.yml). It
also writes the snapshot id to include/snapshot.yml and starts a manifest in
out/integrations/<id>/. It exits 3 when nothing changed since the snapshot `latest` names.

`record --result green` publishes out/snapshots/<id>/ (manifest, compressed image,
SHA256SUMS) and moves the `latest` pointer (out/snapshots/latest.json) to it. It then
commits the refs and tags the commit `snapshot-<id>` (§17.4), unless the tree has
uncommitted changes outside the refs files, so tags always match real history. The resolved
refs stay in the working tree: it always holds the pins of `latest`. `record --result
failed` keeps the manifest and serial log, and restores the files resolve changed.

`resolve --frozen` keeps every tracked component at the commit the snapshot `latest`
recorded, without asking upstream: a development cycle that tests a structural change on a
source set the cache already holds (docs/decisions.md D49). Its manifest says so
(`mode: frozen`, `frozen_from`), and a green frozen cycle is a snapshot like any other. The
next unfrozen cycle moves everything to HEAD on its own, so an upstream regression is never
mixed into a structural step.

`record --result aborted` closes an interrupted cycle: like `failed`, it restores the refs
and publishes nothing, but it makes no claim about the inputs.

An override whose FDSDK original changed fails the cycle at resolve (§31.4).

Both results record the SELinux state and the AVC denials seen on the serial console
(docs/security.md §15: Stage 0 records them without gating on them).

Runs in the builder: needs bst, git, zstd and ruamel.yaml.
"""

import argparse
import copy
import datetime
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import struct
import urllib.request
import zlib

from ruamel.yaml import YAML

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POLICY = os.path.join(REPO, "policy", "tracking.toml")
SNAPSHOT_YML = os.path.join(REPO, "include", "snapshot.yml")
OUT = os.path.join(REPO, "out")
INTEGRATIONS = os.path.join(OUT, "integrations")
SNAPSHOTS = os.path.join(OUT, "snapshots")
CHANNELS = os.path.join(OUT, "channels")
                                                                          
KEEP_UPDATE_ARTIFACTS = 2
CURRENT = os.path.join(INTEGRATIONS, "current")
LATEST = os.path.join(SNAPSHOTS, "latest.json")
MIRRORS = os.path.expanduser("~/.cache/beamline/mirrors")
PROJECT = "beamline"

                                                                                             
STATEFUL = ["project.refs", "junction.refs", "include/kernel/linux-commit.yml", "include/posix-devel/emacs-commit.yml", "include/snapshot.yml"]
SELECTION_FILES = [f for f in STATEFUL if f != "include/snapshot.yml"]

DESCRIBE = re.compile(r"^(?P<tag>.+)-(?P<distance>\d+)-g(?P<sha>[0-9a-f]{40})$")
SHA = re.compile(r"^[0-9a-f]{40}$")
NO_CHANGE = 3
RESOLVE_FAILED = 4


def log(msg):
    print(f"integrate: {msg}", file=sys.stderr, flush=True)


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, text=True, capture_output=True, **kw).stdout.strip()


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


                                                                                        

def yaml():
    y = YAML()
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=2, offset=0)                                  
    y.width = 4096                                                      
    return y


def read_ref(refs_file, element):
    with open(os.path.join(REPO, refs_file), encoding="utf-8") as f:
        data = yaml().load(f) or {}
    entries = data.get("projects", {}).get(PROJECT, {}).get(element) or []
    return entries[0].get("ref") if entries else None


def write_ref(refs_file, element, ref):
    path = os.path.join(REPO, refs_file)
    y = yaml()
    with open(path, encoding="utf-8") as f:
        data = y.load(f) or {}
    elements = data.setdefault("projects", {}).setdefault(PROJECT, {})
    entries = elements.get(element) or [{}]
    entries[0] = {"ref": ref}                                                             
    elements[element] = entries
    with open(path, "w", encoding="utf-8") as f:
        y.dump(data, f)


def source_entries(refs_file, element):
    with open(os.path.join(REPO, refs_file), encoding="utf-8") as f:
        data = yaml().load(f) or {}
    return copy.deepcopy(data.get("projects", {}).get(PROJECT, {}).get(element, []))


def write_source_entries(refs_file, entries, remove=()):
                                                                                
    path = os.path.join(REPO, refs_file)
    y = yaml()
    with open(path, encoding="utf-8") as f:
        data = y.load(f) or {}
    elements = data.setdefault("projects", {}).setdefault(PROJECT, {})
    for element in remove:
        elements.pop(element, None)
    elements.update(entries)
    with open(path, "w", encoding="utf-8") as f:
        y.dump(data, f)


def migrate_sources(policy):
    for name, comp in policy["component"].items():
        for new, old in comp.get("renamed_from", {}).items():
            if new not in comp["elements"]:
                sys.exit(f"integrate: {name}: renamed destination {new} is not a component element")
            before = source_entries(comp["refs"], old)
            after = source_entries(comp["refs"], new)
            if before and after and before != after:
                sys.exit(f"integrate: {name}: conflicting refs for renamed {old} and {new}")
            if before:
                write_source_entries(comp["refs"], {new: before}, remove=(old,))
                log(f"migrated {old} to {new}, preserving all source refs")


def introduce_component(name, comp, arch):
                                                                                          
    fingerprint = hashlib.sha256(json.dumps(comp, sort_keys=True).encode()).hexdigest()
    path = os.path.join(OUT, "source-intake", name, fingerprint + ".json")
    intake = load_json(path) if os.path.isfile(path) else None
    if intake:
        if comp.get("select") == "github-archive":
            write_variable(comp["commit_file"], comp["commit_variable"], intake["source"]["commit"])
        write_source_entries(comp["refs"], intake["entries"])
        log(f"reusing first intake of {name} at {intake['source']['selected_ref']}")
    else:
        source = resolve_component(name, comp, arch)
        source.pop("mirror", None)
        source["introduced_at"] = utcnow().isoformat()
        intake = {"source": source,
                  "entries": {e: source_entries(comp["refs"], e) for e in comp["elements"]}}
        write_json(path, intake)
    return dict(intake["source"], status="INTRODUCED")


def fixed_sources(policy, previous, frozen):
                                                                                         
    sources = {}
    for name, source in policy.get("archive", {}).items():
        digest = source["sha256"]
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            sys.exit(f"integrate: {name}: invalid archive SHA256")
        if not source.get("reason") or not source.get("url"):
            sys.exit(f"integrate: {name}: an archive needs its canonical URL and reason")
        old = (previous or {}).get("archives", {}).get(name)
        if frozen and old and (old["sha256"], old["url"]) != (digest, source["url"]):
            sys.exit(f"integrate: --frozen cannot change archive {name}")
        for element in source["elements"]:
            with open(os.path.join(REPO, "elements", element), encoding="utf-8") as f:
                recipe = yaml().load(f)
            configured = recipe["sources"][0]["url"]
            if "://" not in configured:
                alias, suffix = configured.split(":", 1)
                with open(os.path.join(REPO, "include", "aliases.yml"), encoding="utf-8") as f:
                    aliases = yaml().load(f)
                configured = aliases[alias] + suffix
            if configured != source["url"]:
                sys.exit(f"integrate: {name}: {element} URL differs from the archive policy")
            held = read_ref(source["refs"], element)
            if held is None:
                write_ref(source["refs"], element, digest)
            elif held != digest:
                sys.exit(f"integrate: {name}: {element} has {held}, expected {digest}")
        sources[name] = dict(source, status="FROZEN" if frozen and old else "FIXED")
    return sources


def lockfile_sources(policy, check=False):
                                                                                              

                                                                                             
                                                                                             
       
    resolved = {}
    for name, entry in policy.get("lockfile", {}).items():
        path = os.path.join(REPO, entry["lockfile"])
        with open(path, "rb") as f:
            lock = tomllib.load(f)
        crates = []
        for package in lock.get("package", []):
            source = package.get("source")
            if source is None:
                continue                                                  
            if source != "registry+https://github.com/rust-lang/crates.io-index":
                sys.exit(f"integrate: {name}: unsupported Cargo source {source}")
            checksum = package.get("checksum", "")
            if not re.fullmatch(r"[0-9a-f]{64}", checksum):
                sys.exit(f"integrate: {name}: {package['name']} has no valid checksum")
            crates.append({"name": package["name"], "version": package["version"], "sha": checksum})
        crates.sort(key=lambda c: (c["name"], c["version"]))
        with open(os.path.join(REPO, "elements", entry["element"]), encoding="utf-8") as f:
            recipe = yaml().load(f)
        sources = recipe.get("sources", [])
        if [s["kind"] for s in sources] != ["local", "cargo"]:
            sys.exit(f"integrate: {name}: expected local source followed by cargo")
        wanted = [{}, {"ref": crates}]
        if check:
            if source_entries(entry["refs"], entry["element"]) != wanted:
                sys.exit(f"integrate: {name}: Cargo.lock and {entry['refs']} disagree; run integration resolution")
        else:
            write_source_entries(entry["refs"], {entry["element"]: wanted})
        with open(path, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        resolved[name] = dict(entry, sha256=digest, crates=crates, status="FIXED")
    return resolved


def inherit_recipe(recipe, original, name):
                                                                                                
                                                                                  
    upstream = original["sources"]
    ours = recipe["sources"]
    if len(ours) < len(upstream):
        sys.exit(f"integrate: {name}: override dropped an upstream source")
    entries = []
    for source, copied in zip(upstream, ours):
        expected = {k: v for k, v in source.items() if k != "ref"}
        actual = {k: v for k, v in copied.items() if k != "ref"}
        if expected != actual or ("ref" not in source and source["kind"] != "local"):
            sys.exit(f"integrate: {name}: override sources differ from the selected recipe")
        entries.append({"ref": copy.deepcopy(source["ref"])} if "ref" in source else {})
    for source in ours[len(upstream):]:
        if source["kind"] != "patch" or "ref" in source:
            sys.exit(f"integrate: {name}: only local patches may follow inherited sources")
        entries.append({})
    return entries


def inherited_recipes(policy, sources, previous, frozen, arch):
                                                                                             
    recipes = {}
    for name, entry in policy.get("recipe", {}).items():
        selected = sources[entry["component"]]
        with tempfile.TemporaryDirectory(prefix="beamline-recipes-") as scratch:
            checkout = os.path.join(scratch, "source")
            subprocess.run(["bst", "--no-colors", "--option", "arch", arch,
                            "source", "checkout", "--deps", "none", "--directory", checkout,
                            entry["junction"]], cwd=REPO, check=True, stdout=subprocess.DEVNULL)
            suffix = os.path.join("elements", entry["upstream_element"])
            matches = [os.path.join(root, file) for root, _, files in os.walk(checkout)
                       for file in files if os.path.join(root, file).endswith(os.sep + suffix)]
            if len(matches) != 1:
                sys.exit(f"integrate: {name}: expected one selected upstream recipe, got {matches}")
            with open(matches[0], encoding="utf-8") as f:
                original = yaml().load(f)
        with open(os.path.join(REPO, "elements", entry["element"]), encoding="utf-8") as f:
            recipe = yaml().load(f)
        wanted = inherit_recipe(recipe, original, name)
        held = source_entries(entry["refs"], entry["element"])
        old = (previous or {}).get("inherited_recipes", {}).get(name)
        if frozen and ((held and held != wanted) or (old and old["sources"] != held)):
            sys.exit(f"integrate: --frozen: {name} source refs differ from the selected junction")
        write_source_entries(entry["refs"], {entry["element"]: wanted})
        recipes[name] = dict(entry, junction_commit=selected["commit"], sources=wanted)
        log(f"{name} inherits all sources from {entry['component']} {selected['commit'][:12]}")
    return recipes


def commit_of(ref):
    m = DESCRIBE.match(ref)
    if m:
        return m.group("sha")
    if SHA.match(ref):
        return ref
    sys.exit(f"integrate: cannot read a commit from ref {ref!r}")


def nearest_tag(ref):
    m = DESCRIBE.match(ref)
    return f"{m.group('tag')}-{m.group('distance')}-g{m.group('sha')[:12]}" if m else None


                                                                                        

def ls_remote(url, branch, attempts=4):
                                                                                             
                                                                               
    for attempt in range(1, attempts + 1):
        try:
            out = run(["git", "ls-remote", url, f"refs/heads/{branch}"])
        except subprocess.CalledProcessError as e:
            out = ""
            error = (e.stderr or "").strip().splitlines()[-1:] or [f"exit {e.returncode}"]
            print(f"integrate: {url}: {error[0]} (attempt {attempt} of {attempts})", file=sys.stderr)
        if out:
            return out.split()[0]
        if attempt < attempts:
            time.sleep(10 * attempt)
    sys.exit(f"integrate: {url} gave no head for branch {branch} after {attempts} attempts")


def gitlab_ci_green(project, branch, api="https://gitlab.com"):
    url = (f"{api}/api/v4/projects/{project.replace('/', '%2F')}"
           f"/pipelines?ref={branch}&status=success&per_page=1")
    with urllib.request.urlopen(url, timeout=60) as resp:
        pipelines = json.load(resp)
    if not pipelines:
        sys.exit(f"integrate: no successful pipeline on {project} {branch}")
    return pipelines[0]["sha"]


def mirror(name, url, branch):
                                                                              
    path = os.path.join(MIRRORS, f"{name}.git")
    if not os.path.isdir(path):
        os.makedirs(MIRRORS, exist_ok=True)
        run(["git", "init", "--bare", "--quiet", path])
        run(["git", "-C", path, "remote", "add", "origin", url])
        run(["git", "-C", path, "config", "remote.origin.promisor", "true"])
        run(["git", "-C", path, "config", "remote.origin.partialclonefilter", "tree:0"])
    run(["git", "-C", path, "fetch", "--quiet", "--filter=tree:0", "--tags", "--force",
         "origin", f"+refs/heads/{branch}:refs/heads/{branch}"])
    return path


def github_nearest_tag(repo, sha):
                                                                                            
                                                                                   
    try:
        with urllib.request.urlopen(f"https://raw.githubusercontent.com/{repo}/{sha}/Makefile",
                                    timeout=60) as resp:
            head = resp.read(4096).decode()
        v = dict(re.findall(r"^(VERSION|PATCHLEVEL|SUBLEVEL|EXTRAVERSION) = ?(.*)$", head, re.M))
        tag = f"v{v['VERSION']}.{v['PATCHLEVEL']}"
        tag += (f".{v['SUBLEVEL']}" if v.get("SUBLEVEL", "0") != "0" else "") + v.get("EXTRAVERSION", "")
        with urllib.request.urlopen(f"https://api.github.com/repos/{repo}/compare/{tag}...{sha}",
                                    timeout=60) as resp:
            ahead = json.load(resp)["ahead_by"]
        return f"{tag}-{ahead}-g{sha[:12]}"
    except (OSError, KeyError, ValueError) as exc:
        log(f"warning: no nearest tag for {repo} {sha[:12]}: {exc}")
        return None


def describe(path, sha):
    return run(["git", "-C", path, "describe", "--tags", "--long", "--abbrev=40", sha])


def lag(path, selected, head):
    return int(run(["git", "-C", path, "rev-list", "--count", f"{selected}..{head}"]))


                                                                                        

def bst_track(arch, elements):
    if elements:
        subprocess.run(["bst", "--no-colors", "--option", "arch", arch, "source", "track",
                        "--deps", "none", *elements], cwd=REPO, check=True)


def write_variable(rel, variable, value):
                                                                                   
    path = os.path.join(REPO, rel)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    text, count = re.subn(rf"^  {re.escape(variable)}: .*$", f"  {variable}: {value}", text, flags=re.M)
    if count != 1:
        sys.exit(f"integrate: {rel} has no `{variable}:` to set")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def read_variable(rel, variable):
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        m = re.search(rf"^  {re.escape(variable)}: (.*)$", f.read(), flags=re.M)
    if not m:
        sys.exit(f"integrate: {rel} has no `{variable}:`")
    return m.group(1).strip()


def resolve_archive(name, comp, arch):
                                                                                            
                                                                                              
                                                                             
    url, branch, repo = comp["url"], comp["branch"], comp["github"]
    head = ls_remote(url, branch)
    github_head = ls_remote(f"https://github.com/{repo}.git", branch)
    entry = {"tracking": branch, "head_at_resolution": head, "lag_commits": 0,
             "archive": f"github.com/{repo}"}
    if github_head != head:
        entry["github_head_at_resolution"] = github_head
        log(f"warning: {name}: github.com/{repo} {branch} is at {github_head[:12]}, "
            f"{url} at {head[:12]}")
    pin = comp.get("pin")
    if pin:
        sha = pin["ref"]
        entry.update(status="PINNED", lag_commits=None,
                     pin={k: pin[k] for k in ("reason", "issue") if k in pin})
    else:
        sha = head
        entry["status"] = "HEAD"
    write_variable(comp["commit_file"], comp["commit_variable"], sha)

    bst_track(arch, comp["elements"])
    refs_seen = {read_ref(comp["refs"], e) for e in comp["elements"]}
    if len(refs_seen) != 1:
        sys.exit(f"integrate: {name}: elements resolved to different refs {refs_seen}")
    entry.update(selected_ref=sha, commit=sha, nearest_tag=github_nearest_tag(repo, sha),
                 source=f"https://github.com/{repo}/archive/{sha}.tar.gz",
                 archive_sha256=refs_seen.pop())
    return entry


def resolve_component(name, comp, arch):
    if comp.get("select") == "github-archive":
        return resolve_archive(name, comp, arch)
    url, branch, elements, refs = comp["url"], comp["branch"], comp["elements"], comp["refs"]
    head = ls_remote(url, branch)
    entry = {"tracking": branch, "head_at_resolution": head, "lag_commits": None}
    pin = comp.get("pin")
    select = comp.get("select", "head")

    if pin:
        ref = pin["ref"]
        entry.update(status="PINNED", pin={k: pin[k] for k in ("reason", "issue") if k in pin})
        for element in elements:
            write_ref(refs, element, ref)
        if select == "gitlab-ci-green" or comp.get("mirror"):
            entry["lag_commits"] = lag(mirror(name, url, branch), commit_of(ref), head)
    elif select == "gitlab-ci-green":
        sha = gitlab_ci_green(comp["gitlab_project"], branch, comp.get("gitlab_api", "https://gitlab.com"))
        path = mirror(name, url, branch)
        ref = describe(path, sha)
        for element in elements:
            write_ref(refs, element, ref)
        entry.update(status="HEAD", lag_commits=lag(path, sha, head), selection="newest upstream CI-green commit")
        entry["mirror"] = path
    else:
        for attempt in (1, 2):
            bst_track(arch, elements)
            refs_seen = {read_ref(refs, e) for e in elements}
            if len(refs_seen) != 1:
                sys.exit(f"integrate: {name}: elements resolved to different refs {refs_seen}")
            ref = refs_seen.pop()
            if commit_of(ref) == head:
                break
            head = ls_remote(url, branch)                                                  
            entry["head_at_resolution"] = head
        else:
            sys.exit(f"integrate: {name}: tracked {ref}, but {branch} is at {head}. Does the "
                     f"element's `track:` follow the policy branch?")
        entry.update(status="HEAD", lag_commits=0)

    entry.update(selected_ref=ref, commit=commit_of(ref), nearest_tag=nearest_tag(ref))
    return entry


OVERRIDES = os.path.join(REPO, "elements", "overrides")


def recipe_changed(mirror, old, new, path):
                                                                                              
                          
    def without_refs(commit):
        try:
            recipe = yaml().load(run(["git", "-C", mirror, "show", f"{commit}:{path}"])) or {}
        except subprocess.CalledProcessError:
            return None
        for source in recipe.get("sources", []):
            if isinstance(source, dict):
                source.pop("ref", None)
        return recipe
    return without_refs(old) != without_refs(new)


def copied_local_sources(text, mirror, sha):
                                                                                                 
    paths = [s["path"] for s in (yaml().load(text) or {}).get("sources", [])
             if isinstance(s, dict) and s.get("kind") == "local"]
    return [p for p in paths if run(["git", "-C", mirror, "ls-tree", sha, "--", p])]


def local_copy_differs(mirror, commit, path):
    from pathlib import Path
    registry = Path(REPO, "policy/overrides.toml")
    copies = tomllib.loads(registry.read_text()).get("copy", {}) if registry.exists() else {}
    listing = subprocess.check_output(["git", "-C", mirror, "ls-tree", "-rz", commit, "--", path])
    theirs = {}
    for record in listing.split(b"\0"):
        if not record:
            continue
        header, name = record.split(b"\t", 1)
        mode, _, oid = header.decode().split()
        name = os.fsdecode(name)
        data = subprocess.check_output(["git", "-C", mirror, "cat-file", "blob", oid])
        theirs[name] = (mode, hashlib.sha256(data).hexdigest())
    ours = {}
    for root, directories, files in os.walk(os.path.join(REPO, path)):
        for file in files + [d for d in directories if os.path.islink(os.path.join(root, d))]:
            full = os.path.join(root, file)
            name = os.path.relpath(full, REPO)
            if os.path.islink(full):
                ours[name] = ("120000", hashlib.sha256(os.fsencode(os.readlink(full))).hexdigest())
            else:
                mode = "100755" if os.stat(full).st_mode & 0o111 else "100644"
                ours[name] = (mode, hashlib.sha256(Path(full).read_bytes()).hexdigest())
    if ours.keys() != theirs.keys():
        return True
    for name in ours:
        record = copies.get(name)
        if record:
            if (theirs[name] != (record["mode"], record["upstream_sha256"])
                    or ours[name] != (record["mode"], record["local_sha256"])):
                return True
        elif ours[name] != theirs[name]:
            return True
    return False


def override_drift(upstreams):
                                                                                             
                                                                                              
                                                                                               
                                         
    if not os.path.isdir(OVERRIDES):
        return []
    warnings = []
    with open(os.path.join(REPO, "policy/overrides.toml"), "rb") as f:
        registry = tomllib.load(f)["override"]
    names = set(os.listdir(OVERRIDES))
    if names != set(registry):
        raise ValueError("override provenance must cover exactly elements/overrides")
    for name in sorted(names):
        with open(os.path.join(OVERRIDES, name), encoding="utf-8") as f:
            text = f.read()
        original = registry[name]
        upstream = upstreams.get(original["project"])
        if not upstream or not upstream.get("mirror"):
            continue
        mirror, sha, commit = upstream["mirror"], original["commit"], upstream["commit"]
        if sha != commit and recipe_changed(mirror, sha, commit, original["path"]):
            warnings.append(f"overrides/{name}: {original['project']} changed {original['path']} since "
                            f"{sha[:12]}; re-copy it from {commit[:12]}")
        for path in copied_local_sources(text, mirror, sha):
            if local_copy_differs(mirror, commit, path):
                warnings.append(f"overrides/{name}: {path} differs from {original['project']}'s at "
                                f"{commit[:12]}; re-copy it")
    return warnings


FDSDK_JUNCTION = os.path.join(REPO, "elements", "junctions", "freedesktop-sdk.bst")
GBM_PREFIX = "junctions/gnome-build-meta.bst:"
                                                                                      
                                                                    
GBM_NOT_CARRIED = {
    "components/_private/systemd-base.bst", "components/systemd.bst",
    "components/systemd-ukify.bst", "components/systemd-libs.bst",
    "components/linux-module-cert.bst",
}


def gbm_override_drift(gbm):
                                                                                      
                                                                                     
    theirs_text = run(["git", "-C", gbm["mirror"], "show", f"{gbm['commit']}:elements/freedesktop-sdk.bst"])
    theirs = {k: v for k, v in yaml().load(theirs_text)["config"]["overrides"].items()
              if k not in GBM_NOT_CARRIED}
    with open(FDSDK_JUNCTION, encoding="utf-8") as f:
        junction = yaml().load(f)
    ours = {k: v[len(GBM_PREFIX):] for k, v in junction["config"]["overrides"].items()
            if isinstance(v, str) and v.startswith(GBM_PREFIX)}
    problems = []
    for key in sorted(set(theirs) | set(ours)):
        if theirs.get(key) != ours.get(key):
            problems.append(f"gnome-build-meta overrides {key} with {theirs.get(key) or 'nothing'}; "
                            f"Beamline's FDSDK junction carries {ours.get(key) or 'nothing'}")
    return problems


def repository_state():
                                                                                         
                                                                       
    commit = run(["git", "-C", REPO, "rev-parse", "HEAD"])
    status = subprocess.run(["git", "-C", REPO, "status", "--porcelain", "--untracked-files=all"],
                            check=True, text=True, capture_output=True).stdout
    changed = sorted(line[3:] for line in status.splitlines() if line[3:] not in STATEFUL)
    fingerprint = hashlib.sha256()
    for rel in changed:
        fingerprint.update(rel.encode() + b"\0")
        path = os.path.join(REPO, rel)
        if os.path.isfile(path):
            with open(path, "rb") as f:
                fingerprint.update(f.read())
    return {"commit": commit, "tree": run(["git", "-C", REPO, "rev-parse", "HEAD^{tree}"]),
            "dirty": bool(changed), "changed_files": changed,
            "uncommitted_sha256": fingerprint.hexdigest() if changed else None}


def provenance():
    def quiet(cmd):
        try:
            return run(cmd).splitlines()[0]
        except (OSError, subprocess.CalledProcessError, IndexError):
            return None
    osrel = {}
    if os.path.exists("/etc/os-release"):
        for line in open("/etc/os-release", encoding="utf-8"):
            k, _, v = line.strip().partition("=")
            osrel[k] = v.strip('"')
    return {
        "buildstream": quiet(["bst", "--version"]),
        "buildbox": quiet(["buildbox-casd", "--version"]),
        "builder": osrel.get("PRETTY_NAME"),
        "kernel": platform.release(),
    }


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def latest():
    if not os.path.exists(LATEST):
        return None
    return load_json(os.path.join(SNAPSHOTS, load_json(LATEST)["snapshot"], "manifest.json"))


def write_snapshot_id(value):
    with open(SNAPSHOT_YML, encoding="utf-8") as f:
        text = f.read()
    with open(SNAPSHOT_YML, "w", encoding="utf-8") as f:
        f.write(re.sub(r"^snapshot-id: .*$", f"snapshot-id: {value}", text, flags=re.M))


def backup_dir(snapshot):
    return os.path.join(INTEGRATIONS, snapshot, "before")


def restore(snapshot):
    for rel in STATEFUL:
        src = os.path.join(backup_dir(snapshot), rel)
        if os.path.exists(src):
            shutil.copyfile(src, os.path.join(REPO, rel))


def cmd_resolve(args):
    if os.path.exists(CURRENT):
        sys.exit(f"integrate: integration {open(CURRENT).read().strip()} is still open; "
                 f"run `record` first")
    with open(POLICY, "rb") as f:
        policy = tomllib.load(f)

                                                                                       
    while True:
        now = utcnow()
        snapshot = now.strftime("%Y%m%d.%H%M")
        workdir = os.path.join(INTEGRATIONS, snapshot)
        if not (os.path.exists(workdir) or os.path.exists(os.path.join(SNAPSHOTS, snapshot))):
            break
        log(f"{snapshot} is taken; waiting for the next minute")
        time.sleep(61 - now.second)
    for rel in STATEFUL:
        dest = os.path.join(backup_dir(snapshot), rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(os.path.join(REPO, rel), dest)
    with open(CURRENT, "w") as f:
        f.write(snapshot + "\n")

    try:
        previous = latest()
        migrate_sources(policy)
        archives = fixed_sources(policy, previous, args.frozen)
        lockfiles = lockfile_sources(policy)
        if args.frozen:
            sources = frozen_sources(policy, previous, args.arch)
            drift = []
        else:
            sources = {}
            for name, comp in policy["component"].items():
                log(f"resolving {name} ({comp['branch']})")
                sources[name] = resolve_component(name, comp, args.arch)
            gbm = sources.get("gnome-build-meta", {})
            drift = override_drift({"freedesktop-sdk": sources.get("freedesktop-sdk", {}),
                                    "gnome-build-meta": gbm})
            if gbm.get("mirror"):
                drift += gbm_override_drift(gbm)
            for src in sources.values():
                src.pop("mirror", None)
        recipes = inherited_recipes(policy, sources, previous, args.frozen, args.arch) if not drift else {}
        repo = repository_state()
        same_repo = previous and all(previous["repository"].get(k) == repo[k]
                                     for k in ("commit", "uncommitted_sha256"))
        same_sources = previous and {k: v["selected_ref"] for k, v in previous["sources"].items()} \
            == {k: v["selected_ref"] for k, v in sources.items()}
        same_sources = same_sources and {
            k: (v["url"], v["sha256"]) for k, v in previous.get("archives", {}).items()
        } == {k: (v["url"], v["sha256"]) for k, v in archives.items()}
        if same_repo and same_sources and not (args.force or args.frozen):
            restore(snapshot)
            shutil.rmtree(workdir)
            os.remove(CURRENT)
            log(f"no change since snapshot {previous['snapshot']}")
            return NO_CHANGE

        at_head = sum(1 for v in sources.values() if v["status"] == "HEAD")
        manifest = {
            "snapshot": snapshot,
            "generated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "result": "pending",
            "arch": [args.arch],
            "previous_green": previous["snapshot"] if previous else None,
            "repository": repo,
            "sources": sources,
            "head_conformity": f"{at_head}/{len(sources)}" if not args.frozen
                               else f"frozen at {previous.get('frozen_from', previous['snapshot'])}",
            "fixed": policy.get("fixed", {}),
            "archives": archives,
            "lockfiles": lockfiles,
            "inherited_recipes": recipes,
            "override_drift": drift,
            "provenance": provenance(),
        }
        if args.frozen:
            manifest["mode"] = "frozen"
            manifest["frozen_from"] = previous.get("frozen_from", previous["snapshot"])
        if drift:
            manifest["result"] = "failed"
            manifest["failure"] = "override drift"
            write_json(os.path.join(workdir, "manifest.json"), manifest)
            restore(snapshot)
            os.remove(CURRENT)
            for line in drift:
                log(f"FAILED: {line}")
            log(f"integration {snapshot} FAILED at resolve; record: {workdir}")
            return RESOLVE_FAILED
        write_snapshot_id(snapshot)
        write_json(os.path.join(workdir, "manifest.json"), manifest)
    except BaseException:
        restore(snapshot)
        os.remove(CURRENT)
        raise

    log(f"snapshot candidate {snapshot}: HEAD conformity {manifest['head_conformity']}")
    for name, src in sources.items():
        pinned = f" {src['status']}" if src["status"] != "HEAD" else ""
        log(f"  {name:18} {src['selected_ref']}{pinned}")
    if repo["dirty"]:
        log(f"warning: uncommitted changes outside refs files: {', '.join(repo['changed_files'])}")
    return 0


def frozen_sources(policy, previous, arch=None):
                                                                                             
                                                                                      
    if not previous:
        sys.exit("integrate: --frozen needs a snapshot `latest` to freeze at")
    origin = previous.get("frozen_from", previous["snapshot"])
    sources = {}
    for name, comp in policy["component"].items():
        if name not in previous["sources"]:
            if arch is None:
                sys.exit(f"integrate: --frozen: {name} needs a first source intake")
            log(f"introducing {name} at its designated HEAD; existing components remain frozen")
            sources[name] = introduce_component(name, comp, arch)
            continue
        src = dict(previous["sources"][name])
        if comp.get("select") == "github-archive":
            held = (read_variable(comp["commit_file"], comp["commit_variable"]),
                    {read_ref(comp["refs"], e) for e in comp["elements"]})
            want = (src["commit"], {src["archive_sha256"]})
        else:
            held = {read_ref(comp["refs"], e) for e in comp["elements"]}
            held = held.pop() if len(held) == 1 else held
            want = src["selected_ref"]
        if held != want:
            sys.exit(f"integrate: --frozen: {name} is at {held} in the tree, but snapshot "
                     f"{previous['snapshot']} has {want}; restore its refs first")
        src.update(status="FROZEN", frozen_from=src.get("frozen_from") or
                   (previous["snapshot"] if src.get("introduced_at") else origin))
        sources[name] = src
        log(f"frozen {name} at {src['selected_ref']}")
    return sources


                                                                                        

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


AVC = re.compile(r"avc:\s+denied\s+\{ (?P<perms>[^}]+) \} for .*?"
                 r"scontext=(?P<scontext>\S+) tcontext=(?P<tcontext>\S+) tclass=(?P<tclass>\S+)")
AVC_COMM = re.compile(r"\bcomm=(\"[^\"]*\"|\S+)")
SELINUX_CONFIG = os.path.join(REPO, "files", "selinux", "config")
SELINUX_EXPECTED = os.path.join(REPO, "policy", "selinux-expected.toml")


TEST_LOGS = ("serial.log", "serial-reboot.log", "serial-verity.log", "serial-boot-entries.log",
             "serial-beamlinectl.log",
             "serial-update.log", "serial-shell.log", "serial-run0.log", "serial-settings.log", "serial-security.log",
             "serial-posix.log", "serial-devel.log", "serial-printing.log", "serial-trust.log", "serial-desktop.log",
             "serial-combo-posix.log", "serial-combo-printing.log", "serial-combo-devel.log",
             "serial-combo-all.log", "serial-install-provision.log", "serial-install.log",
             "serial-installed.log", "serial-install-tampered.log", "serial-install-reference.log",
             "serial-update-install.log", "serial-update-reference.log")
TEST_EVIDENCE = TEST_LOGS + ("desktop.ppm",)


def expected_denials():
                                                                                               
    import tomllib
    with open(SELINUX_EXPECTED, "rb") as f:
        entries = tomllib.load(f).get("denial", [])
    for entry in entries:
        missing = {"scontext", "tcontext", "tclass", "perms", "test", "reason"} - set(entry)
        if missing:
            sys.exit(f"integrate: {SELINUX_EXPECTED}: an entry lacks {', '.join(sorted(missing))}")
    return entries


def context_type(context):
    return context.split(":")[2] if context.count(":") >= 3 else context


def is_expected(denial, entries):
    return any(denial["scontext"] == e["scontext"] and denial["tcontext"] == e["tcontext"]
               and denial["tclass"] == e["tclass"] and set(denial["perms"]) <= set(e["perms"])
               and e.get("comm", denial["comm"]) == denial["comm"] for e in entries)


                                                                                                   
                                                                                                 
                 
UPDATE_LOG = "serial-update.log"
KERNEL_BANNER = re.compile(r"\]\s+Linux version ")
BOOTED_VERSION = re.compile(r"\bbooted (\S+) \(old ")


def serial_lines(serial, snapshot):
                                                                                  
    with open(serial, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    if not (snapshot and os.path.basename(serial).endswith(UPDATE_LOG)):
        return lines
    boots, current = [], []
    for line in lines:
        if KERNEL_BANNER.search(line) and current:
            boots.append(current)
            current = []
        current.append(line)
    boots.append(current)
    kept = []
    for boot in boots:
        versions = [m.group(1) for m in map(BOOTED_VERSION.search, boot) if m]
        if versions and versions[0] == snapshot:
            kept.extend(boot)
    return kept


def selinux_summary(serials, snapshot=None):
                                                                                                
                                                                               
    mode = None
    if os.path.exists(SELINUX_CONFIG):
        for line in open(SELINUX_CONFIG, encoding="utf-8"):
            if line.startswith("SELINUX="):
                mode = line.split("=", 1)[1].strip()
    entries = expected_denials()
    denials, unexpected, loaded = set(), set(), False
    for serial in serials:
        if not os.path.exists(serial):
            continue
        for line in serial_lines(serial, snapshot):
            loaded = loaded or "BEAMLINE_SELINUX_OK" in line
                                                                                               
                                     
            for record in re.split(r"(?=avc:\s+denied)", line):
                m = AVC.search(record)
                if not m:
                    continue
                c = AVC_COMM.search(record, m.start())
                comm = c.group(1).strip('"') if c else ""
                text = (f"{{ {m.group('perms')} }} comm={comm} scontext={m.group('scontext')} "
                        f"tcontext={m.group('tcontext')} tclass={m.group('tclass')}")
                denials.add(text)
                denial = {"scontext": context_type(m.group("scontext")),
                          "tcontext": context_type(m.group("tcontext")),
                          "tclass": m.group("tclass"), "perms": m.group("perms").split(),
                          "comm": comm}
                if not is_expected(denial, entries):
                    unexpected.add(text)
    return {"policy_loaded": loaded, "mode": mode, "avc_denials": len(denials),
            "denials": sorted(denials), "unexpected_denials": len(unexpected),
            "unexpected": sorted(unexpected)}


def ppm_to_png(src, dest):
                                                                    
    with open(src, "rb") as f:
        _magic, size, _maxval, pixels = f.read().split(b"\n", 3)
    width, height = map(int, size.split())
    rows = b"".join(b"\x00" + pixels[y * width * 3:(y + 1) * width * 3] for y in range(height))

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    with open(dest, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def keep_evidence(image_dir, dest, prefix=""):
                                                                                                
    for name in TEST_EVIDENCE:
        src = os.path.join(image_dir, name)
        if not os.path.exists(src):
            continue
        if name.endswith(".ppm"):
            ppm_to_png(src, os.path.join(dest, prefix + name[:-4] + ".png"))
        else:
            shutil.copyfile(src, os.path.join(dest, prefix + name))


def publish_update(image_dir, dest, snapshot):
                                                                                             
                                                                                               
                                                                           
    update = os.path.join(image_dir, "update")
    if not os.path.isfile(os.path.join(update, "SHA256SUMS.gpg")):
        log("no update artifacts to publish")
        return
    shutil.copytree(update, os.path.join(dest, "update"))
    os.makedirs(CHANNELS, exist_ok=True)
    link = os.path.join(CHANNELS, "latest")
    tmp = link + ".new"
    if os.path.lexists(tmp):
        os.remove(tmp)
    os.symlink(os.path.join("..", "snapshots", snapshot, "update"), tmp)
    os.replace(tmp, link)
    log(f"channel latest -> snapshot {snapshot}")
    published = sorted(d for d in os.listdir(SNAPSHOTS)
                       if os.path.isdir(os.path.join(SNAPSHOTS, d, "update")))
    for old in published[:-KEEP_UPDATE_ARTIFACTS]:
        shutil.rmtree(os.path.join(SNAPSHOTS, old, "update"))
        log(f"pruned the update artifacts of snapshot {old}")


def changed_since(manifest, previous):
    if not previous:
        return list(manifest["sources"])
    old = {k: v["selected_ref"] for k, v in previous["sources"].items()}
    return [k for k, v in manifest["sources"].items() if old.get(k) != v["selected_ref"]]


def cmd_record(args):
    if not os.path.exists(CURRENT):
        sys.exit("integrate: no open integration; run `resolve` first")
    snapshot = open(CURRENT).read().strip()
    workdir = os.path.join(INTEGRATIONS, snapshot)
    manifest = load_json(os.path.join(workdir, "manifest.json"))
    previous = latest()
    image_dir = os.path.join(OUT, args.arch, "virt")

    manifest["selinux"] = selinux_summary([os.path.join(image_dir, name) for name in TEST_LOGS],
                                          snapshot)
                                                                                           
    gated = False
    unexpected = manifest["selinux"]["unexpected"]
    if args.result == "green" and unexpected:
        log(f"SELinux: {len(unexpected)} unexpected AVC denials; the integration is not green:")
        for denial in unexpected:
            log(f"  {denial}")
        args.result, gated = "failed", True
        manifest["failure"] = "unexpected SELinux denials (policy/selinux-expected.toml)"
    if args.result in ("failed", "aborted"):
        manifest["result"] = args.result
        manifest["changed_since_green"] = changed_since(manifest, previous)
        keep_evidence(image_dir, workdir)
        write_json(os.path.join(workdir, "manifest.json"), manifest)
        restore(snapshot)
        os.remove(CURRENT)
        log(f"integration {snapshot} {args.result.upper()}; latest unchanged "
            f"({previous['snapshot'] if previous else 'none'})")
        log(f"inputs changed since latest: {', '.join(manifest['changed_since_green']) or 'none'}")
        log(f"record: {workdir}")
        return 1 if gated else 0

    dest = os.path.join(SNAPSHOTS, snapshot)
    os.makedirs(dest)
    keep_evidence(image_dir, dest, prefix=f"virt-{args.arch}.")

    manifest["result"] = "green"
    manifest["changed_since_green"] = changed_since(manifest, previous)
                                                                                              
                  
    manifest["artifacts"] = {}
    medium = os.path.join(image_dir, "install", "install.raw")
    mname = f"virt-{args.arch}.install.raw"
    log(f"compressing {mname}")
    subprocess.run(["zstd", "-q", "-T0", "-10", medium, "-o", os.path.join(dest, mname + ".zst")], check=True)
    manifest["artifacts"][mname] = {"sha256": sha256(medium), "zst": mname + ".zst",
                                    "zst_sha256": sha256(os.path.join(dest, mname + ".zst"))}
    write_snapshot_id("dev")
    manifest["git"] = record_in_git(snapshot, args.no_commit)
    write_json(os.path.join(dest, "manifest.json"), manifest)
    with open(os.path.join(dest, "SHA256SUMS"), "w") as f:
        for fname in sorted(os.listdir(dest)):
            if fname != "SHA256SUMS" and os.path.isfile(os.path.join(dest, fname)):
                f.write(f"{sha256(os.path.join(dest, fname))}  {fname}\n")
    publish_update(image_dir, dest, snapshot)
    write_json(LATEST, {"snapshot": snapshot})

    shutil.rmtree(workdir)
    os.remove(CURRENT)
    sel = manifest["selinux"]
    log(f"SELinux: policy {'loaded' if sel['policy_loaded'] else 'NOT loaded'}, {sel['mode']}, "
        f"{sel['avc_denials']} distinct AVC denials recorded, {sel['unexpected_denials']} unexpected")
    conformity = manifest["head_conformity"]
    log(f"snapshot {snapshot} GREEN: latest → {snapshot} "
        f"({conformity if manifest.get('mode') == 'frozen' else conformity + ' at HEAD'})")
    return 0


def record_in_git(snapshot, no_commit):
                                                                                            
            
    tag = f"snapshot-{snapshot}"
    if no_commit:
        log("not recording in git (--no-commit)")
        return {"recorded": False, "reason": "--no-commit"}
    repo = repository_state()
    if repo["dirty"]:
        log(f"not recording {tag} in git: uncommitted changes outside the refs files "
            f"({', '.join(repo['changed_files'])})")
        return {"recorded": False, "reason": "dirty tree"}
    files = SELECTION_FILES
    subprocess.run(["git", "-C", REPO, "add", "--", *files], check=True)
    staged = subprocess.run(["git", "-C", REPO, "diff", "--cached", "--quiet", "--", *files])
    if staged.returncode != 0:
        subprocess.run(["git", "-C", REPO, "commit", "--quiet", "-m", f"snapshot {snapshot}",
                        "--", *files], check=True)
    commit = run(["git", "-C", REPO, "rev-parse", "HEAD"])
    subprocess.run(["git", "-C", REPO, "tag", tag, commit], check=True)
    log(f"recorded {tag} at {commit[:12]}")
    return {"recorded": True, "commit": commit, "tag": tag}


def default_arch():
    machine = platform.machine().lower()
    return {"arm64": "aarch64", "amd64": "x86_64"}.get(machine, machine)


def main():
    parser = argparse.ArgumentParser(description=HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--arch", default=default_arch())
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check-lockfiles", help="check project-owned Cargo lockfile refs without network or writes")
    p = sub.add_parser("resolve", help="pin tracked components and open an integration")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--force", action="store_true", help="integrate even if nothing changed")
    group.add_argument("--frozen", action="store_true",
                       help="keep every tracked component at the commits of `latest` (development cycle)")
    p = sub.add_parser("record", help="close the open integration")
    p.add_argument("--result", choices=["green", "failed", "aborted"], required=True)
    p.add_argument("--no-commit", action="store_true",
                   help="do not commit the refs or tag snapshot-<id> (green only)")
    p = sub.add_parser("classify", help="classify the AVC denials of VM serial logs or exported "
                       "journals against policy/selinux-expected.toml (security §15); exits 1 on "
                       "an unexpected one")
    p.add_argument("logs", nargs="+")
    args = parser.parse_args()
    if args.command == "check-lockfiles":
        with open(POLICY, "rb") as f:
            lockfile_sources(tomllib.load(f), check=True)
        return 0
    if args.command == "classify":
        summary = selinux_summary(args.logs)
        print(json.dumps(summary, indent=2))
        return 1 if summary["unexpected_denials"] else 0
    return cmd_resolve(args) if args.command == "resolve" else cmd_record(args)


if __name__ == "__main__":
    sys.exit(main())
