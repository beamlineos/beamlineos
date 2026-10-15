#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Remove the paths a committed prune list names from a composed tree (docs/decisions.md D88).

  prune-tree.py --tree DIR [--keep-from LIST]... LIST...

Each LIST holds one absolute path pattern per line; `#` starts a comment. In a pattern, `*` and
`?` match within one path component and `**` matches any number of components, so
`/usr/lib/python3.*/**` is everything below Python's library directory. Files and symlinks that
match are removed. Then, until nothing changes:
  - symlinks that pointed at a removed path are removed too (enablement links, `libfoo.so`);
  - directories the removals left empty are removed.

Paths a --keep-from list names are never removed, whatever a prune list says.

A pattern that matches nothing is reported, not an error: an upstream change may have dropped the
file, and the integration cycle should not fail for that.

Standard library only.
"""

import argparse
import os
import re
import sys


def compile_pattern(pattern):
    """A path pattern as a regular expression over absolute paths."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("/**", i) and i + 3 == len(pattern):
            out.append("(?:/.*)?")
            i += 3
        elif pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def read_patterns(paths):
    patterns = []
    for path in paths:
        with open(path, encoding="utf-8") as stream:
            for number, line in enumerate(stream, 1):
                text = line.split("#", 1)[0].strip()
                if not text:
                    continue
                if not text.startswith("/"):
                    sys.exit(f"prune-tree: {path}:{number}: patterns are absolute paths")
                patterns.append((text, compile_pattern(text), f"{os.path.basename(path)}:{number}"))
    return patterns


def entries(tree):
    """Absolute image paths of every file and symlink in the tree."""
    for directory, dirs, files in os.walk(tree):
        for name in files + [d for d in dirs if os.path.islink(os.path.join(directory, d))]:
            yield "/" + os.path.relpath(os.path.join(directory, name), tree)


def link_target(tree, path):
    """The image path a symlink points at, resolved one step."""
    target = os.readlink(tree + path)
    if not target.startswith("/"):
        target = os.path.join(os.path.dirname(path), target)
    return os.path.normpath(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tree", required=True)
    parser.add_argument("--keep-from", action="append", default=[], metavar="LIST")
    parser.add_argument("lists", nargs="+", metavar="LIST")
    args = parser.parse_args()
    tree = os.path.abspath(args.tree)

    patterns = read_patterns(args.lists)
    keep = [regex for _, regex, _ in read_patterns(args.keep_from)]
    matched = {origin: 0 for _, _, origin in patterns}
    removed = set()
    for path in sorted(entries(tree)):
        if any(regex.match(path) for regex in keep):
            continue
        for _, regex, origin in patterns:
            if regex.match(path):
                matched[origin] += 1
                os.unlink(tree + path)
                removed.add(path)
                break

    # Links into removed paths, and the directories left empty, until nothing changes.
    dangling = 0
    while True:
        links = [path for path in entries(tree) if os.path.islink(tree + path)
                 and link_target(tree, path) in removed]
        for path in links:
            os.unlink(tree + path)
            removed.add(path)
        dangling += len(links)
        if not links:
            break
    emptied = 0
    for path in sorted({os.path.dirname(p) for p in removed}, key=len, reverse=True):
        while path not in ("", "/") and os.path.isdir(tree + path) and not os.path.islink(tree + path) \
                and not os.listdir(tree + path):
            os.rmdir(tree + path)
            emptied += 1
            path = os.path.dirname(path)

    for text, _, origin in patterns:
        if not matched[origin]:
            print(f"prune-tree: note: {origin}: {text} matched nothing")
    print(f"prune-tree: removed {len(removed) - dangling} paths, {dangling} links into them, "
          f"{emptied} emptied directories")


if __name__ == "__main__":
    main()
