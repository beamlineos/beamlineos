#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""List what every image of a snapshot contains, read-only (0.0.4.2 step 2A, docs/decisions.md D76).

  content-inventory.py UPDATE-DIR OUTDIR

UPDATE-DIR is a snapshot's channel directory (out/snapshots/<id>/update): SYSTEM's EROFS image
and each extension's sysext and confext. Each image is attached read-only, mounted, and listed
into OUTDIR/<image>.tsv, one line per path:

  path  kind  size  detail

kind is f (file), l (symlink) or d (directory). detail is the link target, `#!interpreter` for a
script, or `elf` for an ELF object. OUTDIR/categories.md then sorts the paths into the
categories the step-2A inspection starts from: build and developer tools, tests, documentation,
interpreters and their scripts, hardware support the Virt profile never uses, duplicates, and
paths several extensions ship with different content. The categories are heuristics: they choose
where to look, the owner decides what leaves.

Needs root for losetup and mount (the builder's passwordless sudo); never writes an image.
"""

import collections
import glob
import os
import re
import subprocess
import sys
import tempfile
import time

KINDS = ("sysext", "confext")


def run(cmd):
    return subprocess.run(cmd, check=True, text=True, capture_output=True).stdout.strip()


def images(update):
    found = {}
    for path in sorted(glob.glob(os.path.join(update, "*.root.raw"))):
        found["system"] = (path, False)
    for path in sorted(glob.glob(os.path.join(update, "*.raw"))):
        name = os.path.basename(path)
        match = re.fullmatch(r"(.+)_[^_]+\.(sysext|confext)\.raw", name)
        if match and match[1] != "admin":  # admin_* are legacy names for posix's bytes (D63)
            found[f"{match[1]}.{match[2]}"] = (path, True)
    return found


def attach(path, partitioned):
    if not partitioned:
        return run(["sudo", "losetup", "-r", "-f", "--show", path]), None
    device = run(["sudo", "losetup", "-P", "-r", "-f", "--show", path])
    for _ in range(20):
        subprocess.run(["sudo", "udevadm", "settle"], check=True)
        for line in run(["lsblk", "-nrpo", "NAME,FSTYPE", device]).splitlines():
            name, _, fstype = line.partition(" ")
            if fstype == "erofs":
                return device, name
        time.sleep(0.5)
    sys.exit(f"content-inventory: no EROFS partition in {path}")


def detail(path):
    try:
        with open(path, "rb") as f:
            head = f.read(256)
    except OSError:
        return ""
    if head.startswith(b"\x7fELF"):
        return "elf"
    if head.startswith(b"#!"):
        line = head[2:].split(b"\n", 1)[0].decode(errors="replace").strip().split()
        if not line:
            return "#!"
        interpreter = line[0]
        if os.path.basename(interpreter) == "env" and len(line) > 1:
            interpreter = line[1]
        return "#!" + os.path.basename(interpreter)
    return ""


def listing(root, out):
    with open(out, "w", encoding="utf-8") as f:
        for dirpath, dirnames, filenames in os.walk(root):
            rel_dir = os.path.relpath(dirpath, root)
            for name in sorted(dirnames):
                p = os.path.join(dirpath, name)
                rel = os.path.normpath(os.path.join(rel_dir, name))
                if os.path.islink(p):
                    f.write(f"/{rel}\tl\t0\t{os.readlink(p)}\n")
                else:
                    f.write(f"/{rel}\td\t0\t\n")
            for name in sorted(filenames):
                p = os.path.join(dirpath, name)
                rel = os.path.normpath(os.path.join(rel_dir, name))
                if os.path.islink(p):
                    f.write(f"/{rel}\tl\t0\t{os.readlink(p)}\n")
                else:
                    f.write(f"/{rel}\tf\t{os.lstat(p).st_size}\t{detail(p)}\n")


def load(path):
    entries = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            p, kind, size, extra = line.rstrip("\n").split("\t")
            entries[p] = (kind, int(size), extra)
    return entries


# Heuristic categories: (title, predicate over (path, kind, size, detail)).
DEV_BIN = re.compile(r"/usr/bin/(g-ir-[^/]+|gdbus-codegen|glib-(compile-resources|genmarshal|mkenums|gettextize)"
                     r"|gtester(-report)?|[^/]*-config|pkg-config|pkgconf|libtool(ize)?|vala[^/]*|vapigen[^/]*"
                     r"|mako-render|markdown_py|gettextize|autopoint|msg[a-z]+|xgettext|intltool[^/]*|itstool"
                     r"|gperf|bison|yacc|flex|m4|make|cmake|meson|ninja|gcc[^/]*|g\+\+|cc|c\+\+|ld(\.[a-z]+)?"
                     r"|as|ar|nm|objdump|objcopy|readelf|strip|gdb|python[0-9.]*-config|icu[a-z]*|gen[a-z]+"
                     r"|pkgdata|derb|makeconv|uconv)$")
CATEGORIES = [
    ("Headers, static libraries, pkg-config, CMake and libtool files",
     lambda p, k, s, d: p.startswith("/usr/include/") or p.endswith((".a", ".la", ".pc", ".cmake"))
     or "/cmake/" in p or "/aclocal/" in p),
    ("Build and developer tools",
     lambda p, k, s, d: bool(DEV_BIN.match(p))),
    ("Introspection data for building (GIR XML, Vala bindings)",
     lambda p, k, s, d: p.startswith(("/usr/share/gir-1.0/", "/usr/share/vala")) ),
    ("Tests and examples",
     lambda p, k, s, d: bool(re.search(r"/(tests?|installed-tests|testsuite|examples?)/", p))
     or bool(re.search(r"[-_]test(s|-tool)?(\.[a-z]+)?$", p))),
    ("Documentation and manuals",
     lambda p, k, s, d: p.startswith(("/usr/share/doc/", "/usr/share/man/", "/usr/share/info/",
                                      "/usr/share/gtk-doc/", "/usr/share/help/"))),
    ("Interpreters",
     lambda p, k, s, d: bool(re.fullmatch(r"/usr/bin/(python[0-9.]*|perl[0-9.]*|bash|lua[0-9.]*|luajit"
                                          r"|tclsh[0-9.]*|ruby|node|gjs|guile[0-9.]*|zsh|ksh|tcsh)", p))),
    ("Python and Perl libraries",
     lambda p, k, s, d: bool(re.match(r"/usr/lib/(python[0-9.]+|perl5)/", p)) or "/perl5/" in p),
    ("Hardware support the Virt profile never uses",
     lambda p, k, s, d: bool(re.search(r"/usr/lib/firmware/|libvulkan_(asahi|broadcom|freedreno|panfrost|radeon"
                                       r"|nouveau|intel)|libdrm_(amdgpu|etnaviv|exynos|freedreno|intel|nouveau"
                                       r"|omap|radeon|tegra)|/dri/(asahi|etnaviv|freedreno|kgsl|lima|panfrost"
                                       r"|panthor|v3d|vc4|nouveau|radeonsi|r300|r600|tegra|imx|rockchip|mediatek"
                                       r"|meson|sun4i|stm|rcar|hx8357d|ili9|mi0283|repaper|st7|pl111|zink)", p))),
]


def categorize(name, entries, out):
    out.write(f"\n## {name}\n\n")
    files = {p: v for p, v in entries.items() if v[0] != "d"}
    total = sum(v[1] for v in files.values())
    out.write(f"{len(files)} files and links, {total / 1048576:.0f} MiB.\n")
    claimed = set()
    for title, predicate in CATEGORIES:
        hits = sorted(p for p, (k, s, d) in files.items() if predicate(p, k, s, d))
        if not hits:
            continue
        claimed.update(hits)
        size = sum(files[p][1] for p in hits)
        out.write(f"\n### {title}: {len(hits)}, {size / 1048576:.1f} MiB\n\n")
        for p in hits[:40]:
            out.write(f"- `{p}`\n")
        if len(hits) > 40:
            out.write(f"- ... {len(hits) - 40} more (see {name}.tsv)\n")
    scripts = collections.Counter(d for k, s, d in files.values() if d.startswith("#!"))
    if scripts:
        out.write("\n### Scripts by interpreter\n\n")
        for interp, count in scripts.most_common():
            present = any(p.endswith("/" + interp[2:]) for p in files)
            out.write(f"- `{interp}`: {count}{'' if present else ' (interpreter not in this image)'}\n")
    big = sorted(files.items(), key=lambda kv: -kv[1][1])[:25]
    out.write("\n### Largest files\n\n")
    for p, (k, s, d) in big:
        out.write(f"- {s / 1048576:.1f} MiB `{p}`\n")


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    update, outdir = sys.argv[1], sys.argv[2]
    os.makedirs(outdir, exist_ok=True)
    found = images(update)
    if "system" not in found:
        sys.exit(f"content-inventory: no SYSTEM image in {update}")
    for name, (path, partitioned) in found.items():
        mountpoint = tempfile.mkdtemp(prefix="beamline-inventory-")
        device, partition = attach(path, partitioned)
        mounted = False
        try:
            run(["sudo", "mount", "-o", "ro", partition or device, mountpoint])
            mounted = True
            # sudo: some files are readable by root only (shadow, polkit rules).
            run(["sudo", sys.executable, os.path.abspath(__file__), "--list", mountpoint,
                 os.path.join(outdir, f"{name}.tsv")])
        finally:
            if mounted:
                run(["sudo", "umount", mountpoint])
            run(["sudo", "losetup", "-d", device])
            os.rmdir(mountpoint)
    loaded = {name: load(os.path.join(outdir, f"{name}.tsv")) for name in found}
    with open(os.path.join(outdir, "categories.md"), "w", encoding="utf-8") as out:
        out.write(f"# Content inventory of {update}\n")
        out.write("\nHeuristic categories: where to look, not what to remove (D76 step 2A).\n")
        sysexts = [n for n in loaded if n.endswith(".sysext")]
        confexts = [n for n in loaded if n.endswith(".confext")]
        for group in (sysexts, confexts):
            shared = collections.defaultdict(dict)
            for n in group:
                for p, (k, s, d) in loaded[n].items():
                    if k != "d" and "extension-release" not in p:
                        shared[p][n] = (k, s, d)
            differ = {p: v for p, v in shared.items() if len(v) > 1 and len(set(v.values())) > 1}
            same = sum(1 for v in shared.values() if len(v) > 1 and len(set(v.values())) == 1)
            out.write(f"\n## Paths in several {'sysexts' if group is sysexts else 'confexts'}\n\n")
            out.write(f"{same} identical (by kind, size and detail); {len(differ)} differ:\n\n")
            for p in sorted(differ):
                out.write(f"- `{p}`: {', '.join(sorted(differ[p]))}\n")
        for name in loaded:
            categorize(name, loaded[name], out)
    print(f"content-inventory: {outdir}/categories.md")


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--list":
        listing(sys.argv[2], sys.argv[3])
    else:
        main()
