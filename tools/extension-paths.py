#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
HELP = """No two extensions may ship one path with different content (docs/decisions.md D88).

  extension-paths.py write --out MANIFEST TREE...
  extension-paths.py compare MANIFEST...

`write` records every file and symlink of an extension's sysext and confext trees: its path, its
kind, and its SHA-256 or link target. `compare` fails when two manifests give one path different
kinds or content. Overlayfs shows only one extension's copy of a path, the last merged, so such a
path would behave differently depending on which extensions are enabled: GNU sed against uutils',
two manual indexes, a linker cache (K7, D82).

Identical copies are fine: extensions are independent (D51) and may share content.

Standard library only.
"""

import argparse
import hashlib
import os
import sys


def write(out, trees):
    lines = []
    for tree in trees:
        for directory, dirs, files in os.walk(tree):
            for name in files + [d for d in dirs if os.path.islink(os.path.join(directory, d))]:
                full = os.path.join(directory, name)
                path = "/" + os.path.relpath(full, tree)
                if os.path.islink(full):
                    lines.append(f"{path}\tlink\t{os.readlink(full)}\n")
                else:
                    digest = hashlib.sha256()
                    with open(full, "rb") as f:
                        for block in iter(lambda: f.read(1 << 20), b""):
                            digest.update(block)
                    lines.append(f"{path}\tfile\t{digest.hexdigest()}\n")
    with open(out, "w", encoding="utf-8") as f:
        f.writelines(sorted(lines))
    print(f"extension-paths: {len(lines)} paths recorded in {out}")


def compare(manifests):
    seen = {}
    for manifest in manifests:
        name = os.path.basename(manifest).split(".")[0]
        with open(manifest, encoding="utf-8") as f:
            for line in f:
                path, kind, content = line.rstrip("\n").split("\t", 2)
                seen.setdefault(path, {})[name] = (kind, content)
    conflicts = {path: owners for path, owners in seen.items() if len(set(owners.values())) > 1}
    for path, owners in sorted(conflicts.items()):
        print(f"extension-paths: {path} differs between {', '.join(sorted(owners))}", file=sys.stderr)
    if conflicts:
        sys.exit(f"extension-paths: {len(conflicts)} path(s) differ between extensions")
    shared = sum(1 for owners in seen.values() if len(owners) > 1)
    print(f"extension-paths: {len(manifests)} extensions, {shared} shared paths, all identical")


def main():
    parser = argparse.ArgumentParser(description=HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    w = commands.add_parser("write")
    w.add_argument("--out", required=True)
    w.add_argument("trees", nargs="+")
    c = commands.add_parser("compare")
    c.add_argument("manifests", nargs="+")
    args = parser.parse_args()
    if args.command == "write":
        write(args.out, args.trees)
    else:
        compare(args.manifests)


if __name__ == "__main__":
    main()
