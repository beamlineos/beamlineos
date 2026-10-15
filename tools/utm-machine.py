#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Create a UTM machine for 0.0.4.1 daily-driver sessions (docs/decisions.md D75).

  tools/utm-machine.py [--snapshot ID] [--out DIR] [--name NAME] ...

The machine is a UTM bundle, out/<arch>/daily/<NAME>.utm by default. Open it in UTM with
`open out/<arch>/daily/<NAME>.utm`. It has a blank disk and, read-only, the snapshot's installer
medium, checked against the snapshot's SHA256SUMS (there is no disk image, D113). On its first
start the medium's installer asks on the serial console which disk to install to; then the
installed disk boots. Its first boot fetches the extensions from an update channel: serve the
snapshot's `update` directory over HTTP and pass its URL as --channel-url (QEMU's shared network
reaches the Mac), or the installed system has no desktop. UTM passes drives to QEMU without a
format, so a raw image would be probed, and QEMU then refuses writes to its first sector; qcow2
avoids that.

The configuration matches what the Virt kernel drives: VirtIO disk, network, GPU (virgl), sound
and RNG, and no USB, balloon or TPM. Firmware without Secure Boot: a TPM would make UTM preload
Microsoft's keys, and the medium would then ask MokManager to enroll Beamline's key first. The extra QEMU arguments come from
`tools/qemu-test.py --utm-arguments`: virtio input devices, the test accounts (dev with a large
home and homed's default shell), and the telemetry sampler. Extension choices use beamlinectl
on the installed system; no boot argument overrides a saved choice.

Needs zstd and qemu-img (Homebrew) on the host. Refuses to replace an existing machine: a session's
disk is its evidence.
"""

import argparse
import hashlib
import json
import os
import plistlib
import random
import shutil
import subprocess
import sys
import tempfile
import uuid

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCH = {"arm64": "aarch64", "amd64": "x86_64"}.get(os.uname().machine, os.uname().machine)


def latest_snapshot():
    with open(os.path.join(REPO, "out", "snapshots", "latest.json"), encoding="utf-8") as f:
        return json.load(f)["snapshot"]


def verify(path):
    name = os.path.basename(path)
    with open(os.path.join(os.path.dirname(path), "SHA256SUMS"), encoding="utf-8") as f:
        expected = {line.split()[1]: line.split()[0] for line in f if line.strip()}
    if name not in expected:
        sys.exit(f"utm-machine: {name} is not listed in the snapshot's SHA256SUMS")
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            digest.update(chunk)
    if digest.hexdigest() != expected[name]:
        sys.exit(f"utm-machine: {path} does not match the snapshot's SHA256SUMS")


def channel_credential(url, path):
    """The transfer definitions pointed at url, as a tmpfiles.extra credential that writes them to
    /run/sysupdate.d (as ci/lib-install.sh does for the tests)."""
    src = os.path.join(REPO, "files", "base", "sysupdate.d")
    with open(path, "w", encoding="utf-8") as out:
        for name in sorted(os.listdir(src)):
            with open(os.path.join(src, name), encoding="utf-8") as f:
                lines = [f"Path={url}\n" if line.startswith("Path=https://") else line
                         for line in f if not line.startswith("#")]
            body = "".join(lines).replace("\\", "\\\\").replace("\n", "\\n").replace("%", "%%")
            out.write(f"f+ /run/sysupdate.d/{name} 0644 - - - {body}\n")


def qemu_arguments(args, image):
    cmd = [sys.executable, os.path.join(REPO, "tools", "qemu-test.py"), "--arch", ARCH,
           "--image", image, "--utm-arguments",
           "--home-size", f"dev={args.home_size}", "--default-shell-user", "dev",
           "--extra-unit", os.path.join(REPO, "tests", "vm", "beamline-telemetry.service"),
           "--extra-unit", os.path.join(REPO, "tests", "vm", "beamline-telemetry.timer"),
           "--credential-file",
           "beamline.test.telemetry-sample=" + os.path.join(REPO, "tests", "vm", "telemetry-sample.sh"),
           "--wants", "beamline-telemetry.timer"]
    with tempfile.TemporaryDirectory() as work:
        if args.channel_url:
            credential = os.path.join(work, "tmpfiles.extra")
            channel_credential(args.channel_url.rstrip("/") + "/", credential)
            cmd += ["--credential-file", f"tmpfiles.extra={credential}"]
        return subprocess.run(cmd, check=True, text=True, capture_output=True).stdout.strip()


def config(args, disk_name, medium_name, arguments):
    mac = "02:" + ":".join(f"{random.randrange(256):02X}" for _ in range(5))
    return {
        "Backend": "QEMU",
        "ConfigurationVersion": 4,
        "Information": {"Name": args.name, "UUID": str(uuid.uuid4()).upper(), "Icon": "linux",
                        "IconCustom": False,
                        "Notes": f"Beamline {args.snapshot}: 0.0.4.1 daily-driver sessions "
                                 "(docs/testing/0.0.4.1-daily-driver.md)."},
        "System": {"Architecture": ARCH, "Target": "virt", "CPU": "default", "CPUCount": args.cpus,
                   "CPUFlagsAdd": [], "CPUFlagsRemove": [], "ForceMulticore": False,
                   "JITCacheSize": 0, "MemorySize": args.memory},
        "QEMU": {"AdditionalArguments": [arguments], "BalloonDevice": False, "DebugLog": False,
                 "Hypervisor": True, "PS2Controller": False, "RNGDevice": True,
                 "RTCLocalTime": False, "TPMDevice": False, "TSO": False, "UEFIBoot": True},
        "Input": {"MaximumUsbShare": 3, "UsbBusSupport": "Disabled", "UsbSharing": False},
        "Sharing": {"ClipboardSharing": False, "DirectoryShareMode": "None",
                    "DirectoryShareReadOnly": False},
        "Display": [{"Hardware": "virtio-gpu-gl-pci", "DynamicResolution": True,
                     "NativeResolution": True, "DownscalingFilter": "Linear",
                     "UpscalingFilter": "Nearest"}],
        "Drive": [{"Identifier": str(uuid.uuid4()).upper(), "ImageName": disk_name,
                   "ImageType": "Disk", "Interface": "VirtIO", "InterfaceVersion": 1,
                   "ReadOnly": False},
                  {"Identifier": str(uuid.uuid4()).upper(), "ImageName": medium_name,
                   "ImageType": "Disk", "Interface": "VirtIO", "InterfaceVersion": 1,
                   "ReadOnly": True}],
        "Network": [{"Hardware": "virtio-net-pci", "Mode": "Shared", "MacAddress": mac,
                     "IsolateFromHost": False, "PortForward": []}],
        "Serial": [{"Mode": "Terminal", "Target": "Auto",
                    "Terminal": {"BackgroundColor": "#000000", "CursorBlink": True, "Font": "Menlo",
                                 "FontSize": 12, "ForegroundColor": "#ffffff"}}],
        "Sound": [{"Hardware": "virtio-sound-pci"}],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshot", help="snapshot ID (default: out/snapshots/latest.json)")
    parser.add_argument("--out", default=os.path.join(REPO, "out", ARCH, "daily"),
                        help="directory for the bundle (default: out/<arch>/daily)")
    parser.add_argument("--name", default="Beamline", help="machine name, and the bundle's file name")
    parser.add_argument("--disk-size", default="128G", help="size of the blank disk to install to")
    parser.add_argument("--channel-url", help="the update channel the installed system fetches its "
                        "extensions from (the snapshot's update directory, served over HTTP)")
    parser.add_argument("--memory", type=int, default=16384, help="RAM in MiB")
    parser.add_argument("--cpus", type=int, default=8)
    parser.add_argument("--home-size", default="64G", help="size of dev's LUKS home")
    args = parser.parse_args()
    for tool in ("zstd", "qemu-img"):
        if not shutil.which(tool):
            sys.exit(f"utm-machine: {tool} not found (brew install {tool.split('-')[0]})")

    args.snapshot = args.snapshot or latest_snapshot()
    image = os.path.join(REPO, "out", "snapshots", args.snapshot, f"virt-{ARCH}.install.raw.zst")
    if not os.path.isfile(image):
        sys.exit(f"utm-machine: {image} not found")
    bundle = os.path.join(args.out, f"{args.name}.utm")
    if os.path.exists(bundle):
        sys.exit(f"utm-machine: {bundle} exists; a session's disk is its evidence, so it is never replaced")

    print(f"utm-machine: checking {image}")
    verify(image)
    arguments = qemu_arguments(args, image)
    data = os.path.join(bundle, "Data")
    os.makedirs(data)
    disk_name, medium_name = "beamline.qcow2", "installer.qcow2"
    raw = os.path.join(data, "installer.raw")
    try:
        print("utm-machine: converting the medium, creating the disk")
        subprocess.run(["zstd", "-q", "-d", image, "-o", raw], check=True)
        subprocess.run(["qemu-img", "convert", "-f", "raw", "-O", "qcow2", raw,
                        os.path.join(data, medium_name)], check=True)
        subprocess.run(["qemu-img", "create", "-q", "-f", "qcow2", os.path.join(data, disk_name),
                        args.disk_size], check=True)
        with open(os.path.join(bundle, "config.plist"), "wb") as f:
            plistlib.dump(config(args, disk_name, medium_name, arguments), f)
    except BaseException:
        shutil.rmtree(bundle, ignore_errors=True)
        raise
    finally:
        if os.path.exists(raw):
            os.remove(raw)
    print(f"utm-machine: created {bundle}\n  open it with: open {bundle!r}")
    print("  To set up a shell, run beamlinectl enable posix --now as a Flatpak terminal command.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
