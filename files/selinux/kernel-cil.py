#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Generate the kernel-defined part of the Beamline CIL policy (docs/decisions.md D35).

The object classes, their permissions and the initial SIDs are defined by the kernel the
policy is loaded into, not by the policy author. They are read from the headers the
project's kernel build installs (classmap.h, initial_sid_to_string.h, security.h), so the
policy always matches the kernel it ships with.

  kernel-cil.py --headers DIR --out kernel.cil --policy-version-file FILE

Emits: classes, classorder, initial SIDs and sidorder, the MCS sensitivity and categories,
the broad allow rules of the platform domains not yet confined (every class except `security`, which policy.cil
grants selectively so that the setenforce/load_policy neverallow holds), and the user
domains' rules on their own sockets.

Standard library only.
"""

import argparse
import os
import re
import sys

CATEGORIES = 1024

# Userspace object managers ask the policy about their own classes (docs/decisions.md D35):
# dbus-broker (dbus) and systemd (service, plus its permissions on the kernel's system
# class). Undeclared, libselinux reports "Unknown class" and an object manager may refuse.
USERSPACE_CLASSES = {
    "dbus": ["acquire_svc", "send_msg"],
    "service": ["start", "stop", "status", "reload", "kill", "load", "enable", "disable"],
}
USERSPACE_PERMS = {
    "system": ["halt", "reboot", "status", "start", "stop", "enable", "disable", "reload", "undefined"],
}


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def classes(classmap):
    text = re.sub(r"/\*.*?\*/", "", classmap, flags=re.S)
    text = text.replace("\\\n", " ")
    macros = dict(re.findall(r"^#define\s+(COMMON_\w+)\s+(.+)$", text, flags=re.M))
    body = text[text.index("secclass_map[]"):]
    body = body[body.index("{") + 1:body.index("};")]
    for _ in range(5):                      # COMMON_FILE_PERMS uses COMMON_FILE_SOCK_PERMS
        for name, value in macros.items():
            body = re.sub(rf"\b{name}\b", value, body)
    result = []
    for name, perms in re.findall(r'\{\s*"([a-z0-9_]+)"\s*,\s*\{([^{}]*)\}\s*\}', body):
        plist = re.findall(r'"([a-z0-9_]+)"', perms)
        if not plist:
            sys.exit(f"kernel-cil: class {name} has no permissions")
        result.append((name, plist))
    if len(result) < 50 or result[0][0] != "security":
        sys.exit(f"kernel-cil: parsed {len(result)} classes; the classmap format changed")
    return result


def initial_sids(table):
    body = table[table.index("initial_sid_to_string[]"):]
    body = body[body.index("{") + 1:body.index("};")]
    sids = []
    for line in body.splitlines():
        line = line.strip()
        m = re.match(r'"([a-z_]+)"', line) or re.match(r"NULL,\s*/\*\s*([a-z_]+)", line)
        if m:
            sids.append((m.group(1), line.startswith('"')))
    sids = sids[1:]                         # index 0 is the unused zero placeholder
    if not sids or sids[0][0] != "kernel":
        sys.exit("kernel-cil: initial_sid_to_string format changed")
    return sids


def policy_version(security_h):
    versions = dict(re.findall(r"^#define\s+(POLICYDB_VERSION_\w+)\s+(\w+)", security_h, flags=re.M))
    value = versions.get("POLICYDB_VERSION_MAX")
    while value in versions:
        value = versions[value]
    if not (value and value.isdigit()):
        sys.exit("kernel-cil: POLICYDB_VERSION_MAX not found")
    return int(value)


# Classes of filesystem objects, and what any domain may do to immutable SYSTEM types in them:
# read and execute, and (directories) change entries, so a settings service can replace its own
# allowlisted file in /etc (docs/decisions.md D56).
FILE_CLASSES = {"file", "dir", "lnk_file", "chr_file", "blk_file", "sock_file", "fifo_file"}
IMMUTABLE_READ = {"read", "getattr", "open", "map", "execute", "execute_no_trans", "ioctl", "lock",
                  "search", "entrypoint", "audit_access", "watch", "watch_mount", "watch_sb",
                  "watch_with_perm", "watch_reads", "mounton"}
DIR_ENTRIES = {"write", "add_name", "remove_name"}
# What platform domains never do to content a lower integrity level can write (DATA, homes,
# temporary and runtime files): execute it (docs/security.md §6.3, §7.4, Stage 1).
EXECUTE = {"execute", "execute_no_trans", "entrypoint", "execmod"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--headers", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--policy-version-file", required=True)
    args = parser.parse_args()

    cls = classes(read(os.path.join(args.headers, "classmap.h")))
    cls = [(name, perms + [p for p in USERSPACE_PERMS.get(name, []) if p not in perms]) for name, perms in cls]
    cls += [(name, perms) for name, perms in USERSPACE_CLASSES.items() if name not in dict(cls)]
    sids = initial_sids(read(os.path.join(args.headers, "initial_sid_to_string.h")))
    version = policy_version(read(os.path.join(args.headers, "security.h")))

    out = ["; Generated by files/selinux/kernel-cil.py from the kernel's SELinux headers.",
           "; Do not edit: classes and initial SIDs belong to the kernel (docs/decisions.md D35).",
           ""]
    out.append("; Object classes in the kernel's order, then userspace object managers' classes")
    for name, perms in cls:
        out.append(f"(class {name} ({' '.join(perms)}))")
    out.append(f"(classorder ({' '.join(n for n, _ in cls)}))")
    out.append("")
    out.append("; Initial SIDs, positional; unused ones keep their place")
    for name, _used in sids:
        out.append(f"(sid {name})")
    out.append(f"(sidorder ({' '.join(n for n, _ in sids)}))")
    out.append("")
    out.append("; MLS: four sensitivities, P0-P3 (docs/security-mls.md §3), and the MCS categories")
    for sens in range(4):
        out.append(f"(sensitivity s{sens})")
    out.append("(sensitivityorder (s0 s1 s2 s3))")
    for i in range(CATEGORIES):
        out.append(f"(category c{i})")
    out.append(f"(categoryorder ({' '.join(f'c{i}' for i in range(CATEGORIES))}))")
    for sens in range(4):
        out.append(f"(sensitivitycategory s{sens} (range c0 c{CATEGORIES - 1}))")
    out.append("")
    out.append("; Platform domains not yet confined (Stage 1: broad until Stage 2; D91) get every class but")
    out.append("; security. On SYSTEM's immutable files (docs/decisions.md D56) they may read, execute and")
    out.append("; change directory entries, never create, write, rename or remove files; content a lower")
    out.append("; integrity level can write they may change but never execute (docs/security.md §6.3).")
    for name, perms in cls:
        if name == "security":
            continue
        if name in FILE_CLASSES:
            out.append(f"(allow beamline_platform_broad_domain beamline_trusted_mutable_type ({name} (all)))")
            data = [p for p in perms if p not in EXECUTE]
            out.append(f"(allow beamline_platform_broad_domain beamline_untrusted_type ({name} ({' '.join(data)})))")
            allowed = [p for p in perms if p in IMMUTABLE_READ or (name == "dir" and p in DIR_ENTRIES)]
            out.append(f"(allow beamline_platform_broad_domain beamline_immutable_file_type ({name} ({' '.join(allowed)})))")
        elif name == "service":
            # PID 1 loads unit files only from labels the policy names (D97, platform.cil).
            out.append("(allow beamline_platform_broad_domain beamline_any_type (service (and (all) (not (load)))))")
        else:
            out.append(f"(allow beamline_platform_broad_domain beamline_any_type ({name} (all)))")
    out.append("")
    out.append("; Sockets: user and admin domains may use every socket class among their own processes.")
    out.append("; Reaching another domain's socket needs a rule in policy.cil.")
    for name, _perms in cls:
        if name == "socket" or name.endswith("_socket"):
            out.append(f"(allow beamline_session_domain self ({name} (all)))")

    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    with open(args.policy_version_file, "w", encoding="utf-8") as f:
        f.write(f"{version}\n")
    print(f"kernel-cil: {len(cls)} classes, {len(sids)} initial SIDs, policy version {version}")


if __name__ == "__main__":
    main()
