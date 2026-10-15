#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Collect a 0.0.4.1 daily-driver session's telemetry from its disk, read-only (decisions D75).

  daily-telemetry.py DISK OUTDIR

DISK is a copy of the machine's disk (raw or qcow2). The machine must be shut down. ci/daily-telemetry
makes a copy-on-write clone of the UTM disk under out/ and runs this in the builder. The disk is
attached read-only with qemu-nbd, and DATA (GPT label `data`) is mounted read-only without journal
replay. OUTDIR receives:

  journal.txt      the whole system journal, every boot (user journals included)
  boots.txt        the boot list and each boot's "Startup finished" line
  failures.txt     failed units and error-level messages
  denials.json     AVC denials, classified against policy/selinux-expected.toml (security §15)
  telemetry.txt    the resource-pressure samples (beamline-telemetry)
  coredumps.txt    crash dumps recorded by systemd-coredump
  extensions.txt   extension activations (posix, printing-scanning, posix-devel, sysext, confext)
  summary.md       the counts, as the start of a findings report

Needs root for qemu-nbd and the mount (the builder's passwordless sudo). Never writes the disk.
"""

import json
import os
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTENSION_UNITS = ["beamline-extension@posix.service", "beamline-extension@printing-scanning.service",
                   "beamline-extension@posix-devel.service", "beamline-extension@desktop-gnome.service",
                   "beamlinectld@*.service", "beamline-extensions-refresh.service",
                   "systemd-sysext.service", "systemd-confext.service"]


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, text=True, **kw)


def output(cmd):
    return subprocess.run(cmd, check=False, text=True, capture_output=True).stdout


def free_nbd():
    run(["sudo", "modprobe", "nbd", "max_part=16"])
    for i in range(16):
        if not os.path.exists(f"/sys/block/nbd{i}/pid"):
            return f"/dev/nbd{i}"
    sys.exit("daily-telemetry: no free /dev/nbd device")


def data_partition(device):
    for _ in range(20):
        run(["sudo", "udevadm", "settle"])
        for line in output(["lsblk", "-nrpo", "NAME,PARTLABEL", device]).splitlines():
            name, _, label = line.partition(" ")
            if label == "data":
                return name
        time.sleep(0.5)
    sys.exit(f"daily-telemetry: no partition labelled `data` on {device}")


def journal(directory, *extra):
    return output(["sudo", "journalctl", "-D", directory, "--no-pager", "-o", "short-iso-precise",
                   *extra])


def collect(mountpoint, outdir):
    journal_dir = os.path.join(mountpoint, "var", "log", "journal")
    if not os.path.isdir(journal_dir):
        sys.exit(f"daily-telemetry: {journal_dir} not found; was the machine ever booted?")
    files = {}
    files["journal.txt"] = journal(journal_dir)
    boots = output(["sudo", "journalctl", "-D", journal_dir, "--no-pager", "--list-boots"])
    startup = [line for line in files["journal.txt"].splitlines() if "Startup finished in" in line]
    files["boots.txt"] = boots + "\n" + "\n".join(startup) + "\n"
    failure_markers = ("Failed with result", "Failed to start", "[FAILED]", "core-dump")
    failed = [line for line in files["journal.txt"].splitlines()
              if any(marker in line for marker in failure_markers)]
    files["failures.txt"] = ("\n".join(failed) + "\n\n== error-level messages\n"
                             + journal(journal_dir, "-p", "err"))
    files["telemetry.txt"] = journal(journal_dir, "-t", "beamline-telemetry")
    files["coredumps.txt"] = output(["sudo", "coredumpctl", "-D", journal_dir, "--no-pager", "list"])
    unit_args = [arg for unit in EXTENSION_UNITS for arg in ("-u", unit)]
    files["extensions.txt"] = journal(journal_dir, *unit_args)
    for name, text in files.items():
        with open(os.path.join(outdir, name), "w", encoding="utf-8") as f:
            f.write(text)

    classify = subprocess.run([sys.executable, os.path.join(REPO, "tools", "integrate.py"), "classify",
                               os.path.join(outdir, "journal.txt")], text=True, capture_output=True)
    with open(os.path.join(outdir, "denials.json"), "w", encoding="utf-8") as f:
        f.write(classify.stdout)
    denials = json.loads(classify.stdout) if classify.stdout.strip() else {}

    coredumps = [line for line in files["coredumps.txt"].splitlines()[1:] if line.strip()]
    samples = [line for line in files["telemetry.txt"].splitlines() if " psi " in line]
    summary = [
        "# 0.0.4.1 session telemetry",
        "",
        f"- boots: {max(len([l for l in boots.splitlines() if l.strip()]) - 1, 0)}",
        f"- \"Startup finished\" lines: {len(startup)}",
        f"- failure lines: {len(failed)}",
        f"- AVC denials: {denials.get('avc_denials', '?')}, "
        f"unexpected: {denials.get('unexpected_denials', '?')} (see denials.json)",
        f"- crash dumps: {len(coredumps)}",
        f"- pressure samples: {len(samples)}",
        "",
        "Unexpected denials:",
        "",
        *[f"- `{d}`" for d in denials.get("unexpected", [])],
        "",
    ]
    with open(os.path.join(outdir, "summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(summary))
    print("\n".join(summary))


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    disk, outdir = sys.argv[1], sys.argv[2]
    fmt = json.loads(output(["qemu-img", "info", "--output=json", "-U", disk]))["format"]
    os.makedirs(outdir, exist_ok=True)
    device = free_nbd()
    mountpoint = tempfile.mkdtemp(prefix="beamline-daily-")
    run(["sudo", "qemu-nbd", "--read-only", f"--format={fmt}", f"--connect={device}", disk])
    mounted = False
    try:
        run(["sudo", "mount", "-o", "ro,noload", data_partition(device), mountpoint])
        mounted = True
        collect(mountpoint, outdir)
    finally:
        if mounted:
            run(["sudo", "umount", mountpoint])
        run(["sudo", "qemu-nbd", "--disconnect", device], stdout=subprocess.DEVNULL)
        os.rmdir(mountpoint)


if __name__ == "__main__":
    main()
