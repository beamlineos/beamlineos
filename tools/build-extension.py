#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Compose a system extension and its configuration extension (docs/spec.md §8,
docs/decisions.md D36).

  build-extension.py --name NAME --tree DIR --base DIR --content-tree DIR [--exclude-tree DIR]
                     [--exclude PATH]... [--regenerated PATH]...
                     --os-id ID --level LEVEL --architecture ARCH --out DIR

--tree is the base plus the extension, composed and integrated together; --base is the
finished root the extension extends. Every path in --tree that the base does not have
becomes extension content: /usr and /opt go to OUT/sysext, /etc to OUT/confext. Paths
from --exclude-tree (the integration toolbox and its runtime closure) are dropped when they
are only there because of the toolbox, as image/root-virt.bst drops them from the root:
a path the extension's own content (--content-tree, the content stack's closure) also has is
kept (readline, which the toolbox closure shares with GNOME Shell), and so is the same path
with other content (uutils' ls where the toolbox has GNU's). Every --exclude path (files the root
removes or replaces by policy, such as su or the update keyring) is dropped. A --regenerated path (a cache built from the
merged tree, such as /etc/ld.so.cache) is extension content even though the base has it: it
shadows the base's copy only while the extension is merged. A path the base has with different content fails the build: an
extension adds to the base, it never replaces it.

Standard library only; runs inside BuildStream.
"""

import argparse
import filecmp
import os
import shutil
import sys
import uuid

SYSEXT_TOPS = ("usr", "opt")
# An image carrying units makes systemd-sysext/confext reload the service manager after
# merging (EXTENSION_RELOAD_MANAGER=1); otherwise PID 1 never sees them.
UNIT_DIRS = ("usr/lib/systemd/system/", "usr/lib/systemd/user/", "etc/systemd/system/", "etc/systemd/user/")
CONFEXT_TOPS = ("etc",)
# Integration may legitimately leave these behind in a composed tree; they belong to
# neither the base nor the extension.
IGNORED_TOPS = ("var", "run", "tmp", "dev", "proc", "sys", "home", "root", "srv", "mnt", "data")


def walk(root):
    """Relative paths of every file and symlink under root (directories are implied)."""
    for dirpath, dirnames, filenames in os.walk(root):
        for name in filenames + [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]:
            yield os.path.relpath(os.path.join(dirpath, name), root)


def same(a, b):
    if os.path.islink(a) or os.path.islink(b):
        return os.path.islink(a) and os.path.islink(b) and os.readlink(a) == os.readlink(b)
    if os.path.isfile(a) and os.path.isfile(b):
        return filecmp.cmp(a, b, shallow=False)
    return False


def copy(src, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.islink(src):
        os.symlink(os.readlink(src), dest)
    else:
        shutil.copy2(src, dest)


def release_file(path, fields):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for key, value in fields:
            f.write(f"{key}={value}\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", required=True)
    parser.add_argument("--tree", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--content-tree", required=True)
    parser.add_argument("--exclude-tree")
    parser.add_argument("--exclude", action="append", default=[], metavar="PATH",
                        help="absolute path to leave out (repeatable)")
    parser.add_argument("--exclude-from", action="append", default=[], metavar="FILE",
                        help="file of exact paths to leave out, with # comments")
    parser.add_argument("--regenerated", action="append", default=[], metavar="PATH",
                        help="absolute path of a cache the extension may regenerate (repeatable)")
    parser.add_argument("--os-id", required=True)
    parser.add_argument("--level", required=True)
    parser.add_argument("--architecture", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    content = set(walk(args.content_tree))
    toolbox = set(walk(args.exclude_tree)) - content if args.exclude_tree else set()
    excluded = {path.lstrip("/") for path in args.exclude}
    for listing in args.exclude_from:
        with open(listing, encoding="utf-8") as stream:
            excluded.update(line.split("#", 1)[0].strip().lstrip("/") for line in stream)
    regenerated = {path.lstrip("/") for path in args.regenerated}
    trees = {"sysext": os.path.join(args.out, "sysext"), "confext": os.path.join(args.out, "confext")}
    counts = {"sysext": 0, "confext": 0}
    has_units = {"sysext": False, "confext": False}
    confext_paths = []
    conflicts, dropped = [], set()

    for rel in sorted(walk(args.tree)):
        top = rel.split(os.sep, 1)[0]
        src, base = os.path.join(args.tree, rel), os.path.join(args.base, rel)
        if rel in excluded:
            continue
        if os.path.lexists(base):
            if same(src, base):
                continue
            if rel not in regenerated:
                conflicts.append(rel)
                continue
        if rel in toolbox and same(src, os.path.join(args.exclude_tree, rel)):
            continue
        if top in SYSEXT_TOPS:
            kind = "sysext"
        elif top in CONFEXT_TOPS:
            kind = "confext"
        elif top in IGNORED_TOPS or os.sep not in rel:
            dropped.add(top)
            continue
        else:
            sys.exit(f"build-extension: {rel}: outside /usr, /opt and /etc")
        copy(src, os.path.join(trees[kind], rel))
        counts[kind] += 1
        has_units[kind] = has_units[kind] or rel.startswith(UNIT_DIRS)
        if kind == "confext":
            confext_paths.append("/" + rel)

    if conflicts:
        for rel in conflicts:
            print(f"build-extension: {args.name}: /{rel} differs from the base", file=sys.stderr)
        sys.exit(f"build-extension: {len(conflicts)} conflicting path(s); an extension must not replace base files")

    reload = lambda kind: [("EXTENSION_RELOAD_MANAGER", "1")] if has_units[kind] else []
    if counts["sysext"]:
        release_file(os.path.join(trees["sysext"], "usr/lib/extension-release.d", f"extension-release.{args.name}"),
                     [("ID", args.os_id), ("SYSEXT_LEVEL", args.level), ("SYSEXT_SCOPE", "system"),
                      ("ARCHITECTURE", args.architecture)] + reload("sysext"))
    if counts["confext"]:
        release_file(os.path.join(trees["confext"], "etc/extension-release.d", f"extension-release.{args.name}"),
                     [("ID", args.os_id), ("CONFEXT_LEVEL", args.level), ("CONFEXT_SCOPE", "system"),
                      ("ARCHITECTURE", args.architecture)] + reload("confext"))
    for kind in trees:
        # Reproducible, distinct filesystem UUIDs per image.
        with open(os.path.join(args.out, f"uuid-{kind}"), "w", encoding="utf-8") as f:
            f.write(f"{uuid.uuid5(uuid.NAMESPACE_URL, f'{args.os_id}:{args.name}:{kind}:{args.level}')}\n")

    print(f"build-extension: {args.name}: {counts['sysext']} sysext and {counts['confext']} confext paths"
          + (f"; ignored {', '.join(sorted('/' + d for d in dropped))}" if dropped else ""))
    if 0 < len(confext_paths) <= 20:
        print(f"build-extension: {args.name} confext: {' '.join(confext_paths)}")


if __name__ == "__main__":
    main()
