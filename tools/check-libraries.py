#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check that every ELF object finds the shared libraries it needs (docs/decisions.md D88).

  check-libraries.py --root ROOT... [--check DIR]... [--allow LIST]

The roots are the system a program runs in, layered as the merge layers them: the base alone, or
the base, then an extension's sysext and confext. A path exists if any root has it. Every ELF
executable and shared object under each --check DIR (default: every root) is read, with its paths
taken relative to that DIR and resolved in the roots. Each DT_NEEDED entry must name a file in
the object's DT_RUNPATH or DT_RPATH directories ($ORIGIN expanded), in the dynamic linker's
directories (those /etc/ld.so.conf names, with its includes, and the default ones), or in the
object's own directory. Failing those, a file of that name anywhere in the roots also counts: a
plugin finds its host's private library (GNOME Software's, Samba's) because the program that loads
the plugin has already loaded it, by soname. What the check catches is a library that no longer
exists at all, which is what removing files breaks.

Pruning removes whole packages' files (0.0.4.2 step 2A); this keeps a removal from breaking a
program that stays. dlopen() is not covered: plugins and loaders name nothing in DT_NEEDED.

An --allow LIST holds `path soname` pairs, each with a reason in a comment, for known gaps.

Standard library only.
"""

import argparse
import glob
import os
import struct
import sys

SKIP_PREFIXES = ("/usr/lib/debug/", "/usr/lib/modules/", "/usr/lib/firmware/", "/usr/src/")
DT_NEEDED, DT_RPATH, DT_RUNPATH = 1, 15, 29
SHT_DYNAMIC = 6


def needed(path):
    """(needed sonames, search paths) of an ELF executable or shared object; None otherwise."""
    try:
        with open(path, "rb") as f:
            ident = f.read(16)
            if len(ident) < 16 or ident[:4] != b"\x7fELF":
                return None
            bits, order = ident[4], {1: "<", 2: ">"}.get(ident[5])
            if bits not in (1, 2) or not order:
                return None
            if bits == 2:
                head = struct.unpack(order + "HHIQQQIHHHHHH", f.read(48))
            else:
                head = struct.unpack(order + "HHIIIIIHHHHHH", f.read(36))
            e_type, shoff, shentsize, shnum = head[0], head[5], head[10], head[11]
            if e_type not in (2, 3) or not shoff or not shnum:   # ET_EXEC, ET_DYN
                return None
            sections = []
            for i in range(shnum):
                f.seek(shoff + i * shentsize)
                if bits == 2:
                    sh = struct.unpack(order + "IIQQQQIIQQ", f.read(64))
                else:
                    sh = struct.unpack(order + "IIIIIIIIII", f.read(40))
                sections.append(sh)   # name, type, flags, addr, offset, size, link, info, align, entsize
            dynamic = [s for s in sections if s[1] == SHT_DYNAMIC]
            if not dynamic:
                return None
            dyn = dynamic[0]
            strtab = sections[dyn[6]]
            f.seek(strtab[4])
            strings = f.read(strtab[5])
            f.seek(dyn[4])
            raw = f.read(dyn[5])
    except OSError:
        return None
    entry = "qQ" if bits == 2 else "iI"
    size = struct.calcsize(order + entry)

    def string(offset):
        end = strings.find(b"\0", offset)
        return strings[offset:end].decode("utf-8", "replace")

    names, search = [], []
    for i in range(0, len(raw) - size + 1, size):
        tag, value = struct.unpack(order + entry, raw[i:i + size])
        if tag == 0:
            break
        if tag == DT_NEEDED:
            names.append(string(value))
        elif tag in (DT_RPATH, DT_RUNPATH):
            search.extend(p for p in string(value).split(":") if p)
    return names, search


def find(roots, path):
    """The host path of an image path in the first root that has it."""
    return next((root + path for root in roots if os.path.lexists(root + path)), None)


def linker_dirs(roots):
    """The dynamic linker's search directories: ld.so.conf (with includes), then defaults."""
    dirs, seen = [], set()

    def read(conf):
        full = find(roots, conf)
        if conf in seen or not full or not os.path.isfile(full):
            return
        seen.add(conf)
        with open(full, encoding="utf-8", errors="replace") as stream:
            for line in stream:
                line = line.split("#", 1)[0].strip()
                if line.startswith("include "):
                    for pattern in line.split()[1:]:
                        if not pattern.startswith("/"):
                            pattern = os.path.join(os.path.dirname(conf), pattern)
                        for root in roots:
                            for match in sorted(glob.glob(root + pattern)):
                                read(match[len(root):])
                elif line:
                    dirs.append(line)

    read("/etc/ld.so.conf")
    for conf in sorted({c[len(r):] for r in roots for c in glob.glob(r + "/etc/ld.so.conf.d/*.conf")}):
        read(conf)
    triplets = {t for r in roots if os.path.isdir(r + "/usr/lib") for t in os.listdir(r + "/usr/lib")}
    for triplet in sorted(triplets):
        if triplet.count("-") >= 2 and triplet.endswith(("-gnu", "-gnueabihf")):
            dirs.append("/usr/lib/" + triplet)
    dirs += ["/usr/lib", "/lib"]
    return dirs


def exists(roots, path):
    """Whether an image path exists in the layered roots, following symlinks across them."""
    for _ in range(40):
        full = find(roots, path)
        if not full:
            return False
        if not os.path.islink(full):
            return True
        target = os.readlink(full)
        path = os.path.normpath(target if target.startswith("/") else os.path.join(os.path.dirname(path), target))
    return False


def read_allow(paths):
    allowed = set()
    for path in paths:
        with open(path, encoding="utf-8") as stream:
            for line in stream:
                words = line.split("#", 1)[0].split()
                if words:
                    if len(words) != 2:
                        sys.exit(f"check-libraries: {path}: expected `path soname`: {line.strip()}")
                    allowed.add(tuple(words))
    return allowed


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", action="append", required=True)
    parser.add_argument("--check", action="append", default=[], metavar="DIR")
    parser.add_argument("--allow", action="append", default=[], metavar="LIST")
    args = parser.parse_args()
    roots = [os.path.abspath(r) for r in args.root]
    dirs = linker_dirs(roots)
    anywhere = {name for root in roots for _, _, files in os.walk(root) for name in files}
    allowed = read_allow(args.allow)

    problems, objects = [], 0
    for top in [os.path.abspath(d) for d in args.check] or roots:
        for directory, _, files in os.walk(top):
            for name in files:
                full = os.path.join(directory, name)
                path = "/" + os.path.relpath(full, top)
                if path.startswith(SKIP_PREFIXES) or os.path.islink(full):
                    continue
                found = needed(full)
                if not found:
                    continue
                objects += 1
                names, search = found
                origin = os.path.dirname(path)
                # The object's own directory too: a private library set (systemd's, Samba's) finds its
                # siblings because the executable that loads them already did, by soname.
                candidates = [s.replace("$ORIGIN", origin).replace("${ORIGIN}", origin) for s in search] \
                    + dirs + [origin]
                for soname in names:
                    if (path, soname) in allowed:
                        continue
                    if "/" in soname:
                        ok = exists(roots, soname if soname.startswith("/") else os.path.join(origin, soname))
                    else:
                        ok = any(exists(roots, os.path.normpath(os.path.join(d, soname))) for d in candidates) \
                            or soname in anywhere
                    if not ok:
                        problems.append(f"{path}: needs {soname}, which no search directory has")

    for problem in sorted(problems):
        print(f"check-libraries: {problem}", file=sys.stderr)
    if problems:
        sys.exit(f"check-libraries: {len(problems)} unresolved librar{'y' if len(problems) == 1 else 'ies'} "
                 f"in {objects} ELF objects")
    print(f"check-libraries: {objects} ELF objects, every needed library found")


if __name__ == "__main__":
    main()
