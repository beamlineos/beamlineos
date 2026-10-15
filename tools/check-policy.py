#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Static policy checks for Beamline trees and unit files (docs/spec.md §2.1, §6, §18.1).

  --units DIR...      Reject shell constructs in Exec*= lines of unit files.
  --tree SYSROOT      The base root: reject user interpreters other than sh/dash, scripts needing
                      absent interpreters, and a non-dash /usr/bin/sh; apply --artifact rules too.
  --artifact TREE...  Any final artifact (root, extension): reject su/sudo/pkexec/doas, package managers,
                      account/privilege helpers, dracut, GNU coreutils binaries (§7.2), web engines
                      (§7.1), setuid/setgid modes and file capabilities except fusermount3 (§22).

Standard library only: this runs on macOS, in the builder VM and inside BuildStream.
"""

import argparse
import ctypes
import errno
import os
import re
import shlex
import subprocess
import stat
import sys

EXEC_KEY = re.compile(r"^\s*(Exec(Start|StartPre|StartPost|Stop|StopPost|Reload|Condition))\s*=\s*(.*)$")

# Constructs that mean "this unit is a shell script" (docs/spec.md §6).
SHELL_CONSTRUCTS = [
    # Exec lines may carry the prefixes - @ : + ! before the binary path.
    (re.compile(r"(^|[\s;@:+!-])(/usr)?/bin/(ba|da)?sh\s+-\w*c"), "shell -c"),
    (re.compile(r"(^|[\s;@:+!-])(ba|da)?sh\s+-\w*c\b"), "shell -c"),
    (re.compile(r"\|\|"), "||"),
    (re.compile(r"&&"), "&&"),
    (re.compile(r"(?<!\|)\|(?!\|)"), "pipe"),
    (re.compile(r"\$\("), "$()"),
    (re.compile(r"`"), "backtick"),
]

UNIT_SUFFIXES = (".service", ".socket", ".timer", ".path", ".mount", ".target")

# docs/spec.md §7.1, docs/decisions.md D29: no web engine or web JavaScript engine.
WEB_ENGINE = re.compile(r"^(libwebkit\S*gtk\S*\.so.*|libjavascriptcoregtk\S*\.so.*|"
                        r"(WebKit|WebKit2|JavaScriptCore)(WebExtension)?-[\d.]+\.typelib|jsc)$")
# docs/spec.md §7.2: shipped coreutils are uutils. GNU binaries carry this in --version;
# uutils' multicall binary also mentions it (in help texts), alongside its own name.
GNU_COREUTILS_MARK = b"GNU coreutils"
UUTILS_MARK = b"uutils"

# Match interpreter entry points, including versioned names and libexec copies.
# Shared libraries (polkit's duktape, for example) are not command interpreters (§5.1).
BASE_INTERPRETER = re.compile(
    r"^(?:python(?:\d+(?:\.\d+)*)?(?:[a-z])?|pypy(?:\d+(?:\.\d+)*)?|"
    r"perl(?:\d+(?:\.\d+)*)?|lua(?:jit)?(?:-?\d+(?:\.\d+)*)?|"
    r"gjs(?:-console)?|node(?:js)?|js\d*|jsc|qjs|d8|duk|"
    r"ruby(?:\d+(?:\.\d+)*)?|irb|tclsh(?:\d+(?:\.\d+)*)?|wish(?:\d+(?:\.\d+)*)?|"
    r"php(?:\d+(?:\.\d+)*)?|raku|R|Rscript|guile(?:-\d+(?:\.\d+)*)?|"
    r"bash|rbash|zsh|ksh(?:\d+)?|mksh|csh|tcsh|fish|ash|busybox|wpexec)$"
)

FORBIDDEN_BINARIES = [
    # Shell policy (docs/spec.md §6) and root identity (§18.1, §19: run0 is the only
    # escalation); bash is base-only
    "bash", "su", "sudo", "pkexec", "doas",
    # The initrd is project-owned (§13)
    "dracut",
    # Package managers and out-of-tree module builds (§2.1)
    "rpm", "dnf", "yum", "microdnf", "zypper", "apt", "apt-get", "dpkg",
    "pacman", "emerge", "apk", "dkms",
    # Image accounts come from sysusers and homed; rootless ID mapping will use a service.
    "newgrp", "passwd", "chsh", "chfn", "gpasswd", "chage", "newuidmap", "newgidmap",
    "useradd", "usermod", "userdel", "groupadd", "groupmod", "groupdel", "chpasswd",
    "pwconv", "pwunconv", "grpconv", "grpunconv", "vipw", "vigr",
]

# §22: the sole temporary exception, restored immediately before filesystem creation.
PRIVILEGE_EXCEPTION = "usr/bin/fusermount3"


def read_capabilities(path):
    if hasattr(os, "getxattr"):
        return os.getxattr(path, "security.capability", follow_symlinks=False)
    if sys.platform != "darwin":
        raise OSError(errno.ENOSYS, "no native extended attribute reader")
    # macOS Python lacks os.getxattr. Darwin's native API takes position and flags
    # as two extra arguments; XATTR_NOFOLLOW is 0x0001 (sys/xattr.h).
    reader = ctypes.CDLL(None, use_errno=True).getxattr
    reader.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p,
                      ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
    reader.restype = ctypes.c_ssize_t
    encoded = os.fsencode(path)
    size = reader(encoded, b"security.capability", None, 0, 0, 1)
    if size < 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), path)
    buffer = ctypes.create_string_buffer(size)
    size = reader(encoded, b"security.capability", buffer, len(buffer), 0, 1)
    if size < 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), path)
    return buffer.raw[:size]


def check_privilege_metadata(tree):
    problems = []
    unsupported = {errno.ENODATA, errno.ENOTSUP, errno.EOPNOTSUPP}
    if hasattr(errno, "ENOATTR"):
        unsupported.add(errno.ENOATTR)
    for directory, dirs, files in os.walk(tree):
        paths = ([directory] if directory == tree else []) + [os.path.join(directory, name) for name in dirs + files]
        for path in paths:
            mode = os.lstat(path).st_mode
            if stat.S_ISLNK(mode):
                continue
            exception = os.path.relpath(path, tree) == PRIVILEGE_EXCEPTION and stat.S_ISREG(mode)
            if mode & (stat.S_ISUID | stat.S_ISGID) and not exception:
                problems.append(f"{path}: setuid/setgid mode {stat.S_IMODE(mode):04o} forbidden (§22)")
            try:
                read_capabilities(path)
            except OSError as exc:
                if exc.errno not in unsupported:
                    problems.append(f"{path}: cannot audit file capabilities: {exc}")
            else:
                if not exception:
                    problems.append(f"{path}: file capabilities forbidden (§22)")
    return problems


def load_allowlist(path):
    allowed = set()
    if not path:
        return allowed
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if line:
                allowed.add(line.split()[0])
    return allowed


def iter_unit_files(roots):
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in sorted(filenames):
                if name.endswith(UNIT_SUFFIXES) or name.endswith(".conf") and dirpath.endswith(".d"):
                    yield os.path.join(dirpath, name)


def logical_lines(path):
    """Yield (lineno, text) with backslash continuations joined."""
    with open(path, encoding="utf-8", errors="replace") as f:
        buf, start = "", None
        for lineno, raw in enumerate(f, 1):
            line = raw.rstrip("\n")
            if start is None:
                start = lineno
            if line.endswith("\\"):
                buf += line[:-1] + " "
                continue
            yield start, buf + line
            buf, start = "", None
        if buf:
            yield start, buf


def check_units(roots, allowlist):
    problems = []
    for path in iter_unit_files(roots):
        # .wants/ links and aliases point at files scanned anyway, and an absolute
        # link inside a sysroot would resolve against the host.
        if os.path.islink(path):
            continue
        if os.path.basename(path) in allowlist:
            continue
        for lineno, line in logical_lines(path):
            m = EXEC_KEY.match(line)
            if not m:
                continue
            command = m.group(3)
            for pattern, label in SHELL_CONSTRUCTS:
                if pattern.search(command):
                    problems.append(f"{path}:{lineno}: {m.group(1)} uses {label}: {command.strip()}")
                    break
    return problems


def check_artifact(tree):
    problems = check_privilege_metadata(tree)
    for bindir in ("usr/bin", "usr/sbin", "usr/local/bin"):
        for name in FORBIDDEN_BINARIES:
            if name != "bash" and os.path.lexists(os.path.join(tree, bindir, name)):
                problems.append(f"{os.path.join(tree, bindir, name)}: must not be in any artifact")
    for dirpath, _dirnames, filenames in os.walk(tree):
        for name in filenames:
            path = os.path.join(dirpath, name)
            if WEB_ENGINE.match(name):
                problems.append(f"{path}: web engine (docs/spec.md §7.1)")
            rel = os.path.relpath(dirpath, tree)
            if rel in ("usr/bin", "usr/sbin") and not os.path.islink(path) and os.path.isfile(path):
                with open(path, "rb") as f:
                    data = f.read()
                # Only programs: scripts such as xz's xzdiff mention GNU coreutils in prose.
                if data[:4] != b"\x7fELF":
                    continue
                if GNU_COREUTILS_MARK in data and not (name == "coreutils" and UUTILS_MARK in data):
                    problems.append(f"{path}: GNU coreutils (shipped coreutils are uutils, §7.2)")
    return problems


def script_interpreter(line):
    """Read a shebang, including env sh and env -S; never evaluate shell input."""
    if not line.startswith(b"#!"):
        return None
    try:
        words = shlex.split(line[2:].decode("utf-8", errors="replace"))
    except ValueError:
        return "invalid shebang"
    if not words:
        return "empty shebang"
    if os.path.basename(words[0]) == "env":
        words = words[1:]
        while words and (words[0].startswith("-") or "=" in words[0]):
            option = words.pop(0)
            if option in ("-u", "--unset") and words:
                words.pop(0)
        return os.path.basename(words[0]) if words else "env without a command"
    return os.path.basename(words[0])


def check_base_interpreters(sysroot):
    problems = []
    for dirpath, _dirnames, filenames in os.walk(sysroot):
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            if BASE_INTERPRETER.fullmatch(name):
                problems.append(f"{path}: user interpreter must not be in the base (§5.1)")
            if os.path.islink(path) or not os.path.isfile(path):
                continue
            if not os.stat(path).st_mode & 0o111:
                continue
            with open(path, "rb") as stream:
                interpreter = script_interpreter(stream.readline(4096))
            if interpreter and interpreter not in ("sh", "dash"):
                problems.append(f"{path}: script requires {interpreter}, absent from the base (§5.1)")
    return problems


def check_tree(sysroot):
    problems = check_artifact(sysroot)
    problems += check_base_interpreters(sysroot)
    for bindir in ("usr/bin", "usr/sbin", "usr/local/bin"):
        for name in FORBIDDEN_BINARIES:
            candidate = os.path.join(sysroot, bindir, name)
            if os.path.lexists(candidate):
                problems.append(f"{candidate}: must not be in the base")

    sh = os.path.join(sysroot, "usr/bin/sh")
    if not os.path.lexists(sh):
        problems.append(f"{sh}: missing (base must provide a POSIX /bin/sh)")
    elif not (os.path.islink(sh) and os.path.basename(os.readlink(sh)) == "dash"):
        target = os.readlink(sh) if os.path.islink(sh) else "a regular file"
        problems.append(f"{sh}: must be a symlink to dash, found {target}")

    bin_link = os.path.join(sysroot, "bin")
    if os.path.lexists(bin_link) and not (os.path.islink(bin_link) and os.readlink(bin_link) == "usr/bin"):
        problems.append(f"{bin_link}: must be a symlink to usr/bin")
    return problems


def image_path(roots, path):
    """Resolve a merged image path, including absolute symlinks, without using host paths."""
    pending = path.split("/")
    resolved = []
    links = 0
    while pending:
        part = pending.pop(0)
        if not part or part == ".":
            continue
        if part == "..":
            if resolved:
                resolved.pop()
            continue
        rel = os.path.join(*resolved, part)
        candidate = next((os.path.join(root, rel) for root in roots
                          if os.path.lexists(os.path.join(root, rel))), None)
        if candidate is None:
            return None
        if os.path.islink(candidate):
            links += 1
            if links > 40:
                return None
            target = os.readlink(candidate)
            if target.startswith("/"):
                resolved = []
            pending = target.split("/") + pending
        else:
            resolved.append(part)
    return next((os.path.join(root, *resolved) for root in roots
                 if os.path.lexists(os.path.join(root, *resolved))), None)


# MLS levels (docs/security-mls.md §3, D99): every context names one of four level ranges. Only
# shared, non-executable types may be low (no category), so that whatever a session executes
# carries its category (invariant I3); range transitions only go down from the platform (Lemma 3).
MLS_RANGES = {"lr_low", "lr_session", "lr_admin", "lr_platform"}
MLS_LOW_TYPES = {"unlabeled_t", "tmp_t", "tmpfs_t", "device_t", "null_device_t", "fuse_device_t",
                 "devpts_t", "mqueue_t", "fs_t", "port_t", "netif_t", "node_t"}
MLS_CONTEXT = re.compile(r"\((system_u|user_u|admin_u) (object_r|system_r) ([a-z0-9_]+) "
                         r"(\(\([^()]*\)[^()]*\([^()]*(?:\([^()]*\))?\)\)|[a-z0-9_]+)\)")


def check_selinux_policy(directory):
    """No permissive domain in the policy (D91): a confined service is developed with
    `typepermissive`, which logs its denials instead of enforcing them, and must never reach a
    cycle like that. Every context's level is one of the named ranges (D99)."""
    problems = []
    for root, _, files in os.walk(directory):
        for name in sorted(files):
            if not name.endswith(".cil"):
                continue
            path = os.path.join(root, name)
            with open(path, encoding="utf-8") as stream:
                for number, line in enumerate(stream, 1):
                    code = line.split(";", 1)[0]
                    if re.match(r"\s*\(typepermissive\b", code):
                        problems.append(f"{path}:{number}: typepermissive: a permissive domain enforces nothing")
                    for match in MLS_CONTEXT.finditer(code):
                        type_, level = match.group(3), match.group(4)
                        if level not in MLS_RANGES:
                            problems.append(f"{path}:{number}: {type_}: level {level} is not a named range (D99)")
                        elif level == "lr_low" and type_ not in MLS_LOW_TYPES:
                            problems.append(f"{path}:{number}: {type_}: only shared, non-executable types are low (I3, D99)")
                    transition = re.match(r"\s*\(rangetransition \S+ \S+ \S+ (\S+)\)", code)
                    if transition and transition.group(1) not in MLS_RANGES - {"lr_platform"}:
                        problems.append(f"{path}:{number}: a range transition must go below the platform (Lemma 3, D99)")
    return problems


def posix_utilities(path, scope):
    entries = {}
    with open(path, encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            words = line.split("#", 1)[0].split()
            if not words:
                continue
            if (len(words) != 4 or words[0] not in ("posix", "posix-devel", "both")
                    or words[1] not in ("command", "builtin")
                    or not re.fullmatch(r"[a-z][a-z0-9-]*", words[2])
                    or not re.fullmatch(r"mandatory|[A-Z]{2,3}(,[A-Z]{2,3})*", words[3])):
                raise ValueError(f"{path}:{number}: expected posix|posix-devel|both command|builtin utility group")
            extensions, provider, name, _group = words
            if extensions in (scope, "both"):
                if name in entries:
                    raise ValueError(f"{path}:{number}: duplicate utility {name}")
                entries[name] = provider
    if not entries:
        raise ValueError(f"{path}: no utilities for {scope}")
    return entries


def check_posix(extension, base, listing, scope):
    problems = []
    try:
        entries = posix_utilities(listing, scope)
    except ValueError as exc:
        return [str(exc)]
    roots = (extension, base)
    for name, provider in entries.items():
        if provider == "builtin":
            continue
        path = image_path(roots, "/usr/bin/" + name)
        if not path or not os.path.isfile(path) or not os.stat(path).st_mode & 0o111:
            problems.append(f"{scope}: missing executable POSIX utility {name} ({listing})")
    bash = image_path(roots, "/usr/bin/bash")
    if not bash:
        problems.append(f"{scope}: missing bash for the required shell builtins")
    else:
        names = [name for name, provider in entries.items() if provider == "builtin"]
        result = subprocess.run(
            [bash, "--noprofile", "--norc", "--posix", "-c",
             'for name do test "$(type -t "$name")" = builtin || printf "%s\\n" "$name"; done',
             "posix-contents", *names],
            env={"PATH": "", "LC_ALL": "C"}, text=True, capture_output=True, check=False)
        if result.returncode:
            problems.append(f"{scope}: bash builtin check failed: {result.stderr.strip()}")
        problems.extend(f"{scope}: missing shell builtin {name}" for name in result.stdout.splitlines())
    if not problems:
        print(f"policy: {scope}: {len(entries)} POSIX utility entries present")
    return problems


def check_extensions(directory):
    """Keep the daemon's immutable catalogue coupled to the shipped update resources."""
    names = {"desktop-gnome", "posix", "posix-devel", "printing-scanning"}
    metadata = os.path.join(directory, "beamline", "extensions.d")
    problems = []
    files = {os.path.splitext(name)[0] for name in os.listdir(metadata) if name.endswith('.conf')}
    if files != names:
        problems.append(f"{metadata}: expected exactly the four official extensions")
    for name in sorted(files):
        path = os.path.join(metadata, name + '.conf')
        values = {}
        for line in open(path, encoding='utf-8'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            key, separator, value = line.partition('=')
            if not separator or key in values:
                problems.append(f"{path}: malformed or repeated key")
            values[key] = value
        if (set(values) != {'Description', 'Live', 'Interactive', 'Default'}
                or not values.get('Description')
                or values.get('Live') not in ('yes', 'no')
                or values.get('Interactive') not in ('yes', 'no')
                or values.get('Default') not in ('enabled', 'disabled')):
            problems.append(f"{path}: invalid extension metadata")
        expected = {'Live': 'no' if name == 'desktop-gnome' else 'yes',
                    'Interactive': 'yes' if name in ('desktop-gnome', 'posix') else 'no',
                    'Default': 'enabled' if name == 'desktop-gnome' else 'disabled'}
        if any(values.get(key) != value for key, value in expected.items()):
            problems.append(f"{path}: flags disagree with the official extension boot policy")
        for kind, prefix in [('sysext', '7'), ('confext', '8')]:
            transfers = [f for f in os.listdir(os.path.join(directory, 'sysupdate.d'))
                         if re.fullmatch(prefix + r'[0-9]-' + re.escape(name) + '-' + kind + r'\.transfer', f)]
            if len(transfers) != 1:
                problems.append(f"{path}: requires exactly one {kind} transfer")
    template = os.path.join(directory, 'systemd/system/beamline-extension@.service')
    if os.path.exists(template):
        preset = open(os.path.join(directory, 'systemd/system-preset/80-beamline.preset'), encoding='utf-8').read()
        instances = [line.split()[2:] for line in preset.splitlines()
                     if line.startswith('enable beamline-extension@.service ')]
        if len(instances) != 1 or set(instances[0]) != names:
            problems.append(f"{template}: preset must enable exactly the official instances")
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--units", nargs="+", default=[], metavar="DIR", help="unit directories to scan")
    parser.add_argument("--tree", metavar="SYSROOT", help="composed root filesystem to check")
    parser.add_argument("--artifact", nargs="+", default=[], metavar="TREE",
                        help="other final artifact trees (extensions) to check")
    parser.add_argument("--allowlist", metavar="FILE", help="unit file names exempt from the shell rule")
    parser.add_argument("--posix-tree", metavar="TREE", help="finished POSIX extension tree")
    parser.add_argument("--posix-base", metavar="TREE", help="finished base accompanying the extension")
    parser.add_argument("--posix-list", metavar="FILE", help="POSIX.1-2024 contents specification")
    parser.add_argument("--posix-scope", choices=("posix", "posix-devel"), default="posix")
    parser.add_argument("--base-user-tools", metavar="FILE", help="commands moved out of the base")
    parser.add_argument("--selinux-policy", metavar="DIR", help="CIL sources to check for permissive domains")
    parser.add_argument("--extensions-policy", metavar="DIR", help="base source catalogue and update resources")
    parser.add_argument("--base-virtualization", metavar="FILE",
                        help="virtualization paths that neither the base nor an extension may ship")
    args = parser.parse_args()

    if not args.units and not args.tree and not args.artifact and not args.posix_tree \
            and not args.selinux_policy and not args.extensions_policy:
        parser.error("nothing to check: pass --units, --tree and/or --artifact")
    if args.posix_tree and not (args.posix_base and args.posix_list):
        parser.error("--posix-tree requires --posix-base and --posix-list")

    problems = []
    if args.extensions_policy:
        problems += check_extensions(args.extensions_policy)
    if args.units:
        problems += check_units(args.units, load_allowlist(args.allowlist))
    if args.selinux_policy:
        problems += check_selinux_policy(args.selinux_policy)
    if args.tree:
        problems += check_tree(args.tree)
        if args.base_user_tools:
            with open(args.base_user_tools, encoding="utf-8") as stream:
                for line in stream:
                    path = line.split("#", 1)[0].strip()
                    if path and image_path((args.tree,), path):
                        problems.append(f"{path}: user-facing command belongs in posix (§7.2)")
    for tree in args.artifact:
        problems += check_artifact(tree)
    if args.base_virtualization:
        with open(args.base_virtualization, encoding="utf-8") as stream:
            listed = [line.split("#", 1)[0].strip() for line in stream]
        for tree in ([args.tree] if args.tree else []) + args.artifact:
            for path in filter(None, listed):
                if image_path((tree,), path):
                    problems.append(f"{path}: virtualization service, reserved for a later "
                                    f"virtualization sysext (D87)")
    if args.posix_tree:
        problems += check_posix(args.posix_tree, args.posix_base, args.posix_list, args.posix_scope)

    for problem in problems:
        print(f"policy: {problem}", file=sys.stderr)
    if problems:
        print(f"policy: {len(problems)} violation(s)", file=sys.stderr)
        return 1
    print("policy: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
