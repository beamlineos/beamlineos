#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Pin system UIDs and GIDs (docs/decisions.md D106, step 0).

  pin-sysusers.py apply TABLE SYSUSERS_DIR   write the table's numbers into every u/g line
  pin-sysusers.py check TABLE ROOT           compare ROOT/etc/passwd and /etc/group with the table

`apply` runs before systemd-sysusers, `check` after it. Both fail on an account the table does
not pin, and `check` also fails on a table line no account uses.
"""

import os
import re
import sys

LINE = re.compile(r"^(\s*)(u!?|g)(\s+)(\S+)(\s+)(\S+)(.*)$")


def load_table(path):
    users, groups = {}, {}
    with open(path, encoding="utf-8") as f:
        for number, line in enumerate(f, 1):
            fields = line.split("#", 1)[0].split()
            if not fields:
                continue
            if fields[0] == "u" and len(fields) == 4:
                uid, gid = int(fields[2]), int(fields[3])
                users[fields[1]] = (uid, gid)
                groups[fields[1]] = gid
            elif fields[0] == "g" and len(fields) == 3:
                groups[fields[1]] = int(fields[2])
            else:
                sys.exit(f"{path}:{number}: expected 'u NAME UID GID' or 'g NAME GID'")
    return users, groups


def pinned_id(kind, name, current, users, groups):
    if kind.startswith("u"):
        if name not in users:
            return None
        uid, gid = users[name]
        # A bare UID makes sysusers create the user's own group with the same number;
        # UID:GID means joining a group that already exists.
        want = str(uid) if uid == gid else f"{uid}:{gid}"
        if current not in ("-", str(uid), f"{uid}:{gid}"):
            sys.exit(f"user {name}: sysusers.d says {current}, the table {want}")
        return want
    if name not in groups:
        return None
    want = str(groups[name])
    if current not in ("-", want):
        sys.exit(f"group {name}: sysusers.d says {current}, the table {want}")
    return want


def apply(table, directory):
    users, groups = load_table(table)
    missing = []
    for conf in sorted(os.listdir(directory)):
        if not conf.endswith(".conf"):
            continue
        path = os.path.join(directory, conf)
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        out = []
        for line in lines:
            m = LINE.match(line.rstrip("\n"))
            if not m:
                out.append(line)
                continue
            indent, kind, s1, name, s2, current, rest = m.groups()
            want = pinned_id(kind, name, current, users, groups)
            if want is None:
                missing.append(f"{conf}: {kind} {name}")
                out.append(line)
                continue
            out.append(f"{indent}{kind}{s1}{name}{s2}{want}{rest}\n")
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(out)
    if missing:
        sys.exit("system accounts without a pinned ID (add them to the table):\n  " + "\n  ".join(missing))


def check(table, root):
    users, groups = load_table(table)
    problems = []
    seen_users, seen_groups = set(), set()
    with open(os.path.join(root, "etc/passwd"), encoding="utf-8") as f:
        for line in f:
            name, _, uid, gid = line.split(":")[:4]
            seen_users.add(name)
            if users.get(name) != (int(uid), int(gid)):
                problems.append(f"passwd: {name} {uid}:{gid}, pinned {users.get(name)}")
    with open(os.path.join(root, "etc/group"), encoding="utf-8") as f:
        for line in f:
            name, _, gid = line.split(":")[:3]
            seen_groups.add(name)
            if groups.get(name) != int(gid):
                problems.append(f"group: {name} {gid}, pinned {groups.get(name)}")
    problems += [f"table: user {n} does not exist" for n in sorted(set(users) - seen_users)]
    problems += [f"table: group {n} does not exist" for n in sorted(set(groups) - seen_groups)]
    if problems:
        sys.exit("system IDs differ from the pinned table:\n  " + "\n  ".join(problems))


def main():
    if len(sys.argv) != 4 or sys.argv[1] not in ("apply", "check"):
        sys.exit(__doc__)
    (apply if sys.argv[1] == "apply" else check)(sys.argv[2], sys.argv[3])


if __name__ == "__main__":
    main()
