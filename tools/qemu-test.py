#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
HELP = """Boot a Beamline disk under QEMU and wait for a serial marker (docs/spec.md §25-29).
Installed disks come from the installer medium (ci/test-install, D113); the examples boot the
reference disk ci/test-install prepares.

The image is never written. Every test boots a throwaway qcow2 overlay (§28). Interactive daily use
(0.0.4.1, D75) may instead keep a persistent overlay (--persist), which also keeps its UEFI
variables; that overlay is backed by the image, which stays read-only.
Installation tests (0.0.4.3, D106) add a TPM (--tpm, swtpm with its state in a directory),
Secure Boot capable firmware starting in setup mode (--secure-boot), UEFI variables kept in a
file across runs (--vars) and a target disk (--disk); --image may then be the installed qcow2.
Under --secure-boot the command-line additions also travel as credentials, which an enforced
Secure Boot does not drop (D111), and --tamper-file breaks a UKI's signature in the overlay.
Acceleration is picked automatically (QEMU_ACCEL=auto|hvf|kvm|tcg, §25):
macOS -> HVF, Linux with a usable /dev/kvm -> KVM, otherwise TCG. --qemu (or QEMU_SYSTEM)
selects another QEMU binary, such as one built with virglrenderer for --gpu gl.

Examples:
  tools/qemu-test.py --image out/aarch64/virt/installed/reference.qcow2
  tools/qemu-test.py --image out/aarch64/virt/installed/reference.qcow2 --interactive
  tools/qemu-test.py --image out/aarch64/virt/installed/reference.qcow2 --interactive --gpu gl \
      --qemu /path/to/qemu-system-aarch64        # a virglrenderer QEMU: accelerated GNOME
  tools/qemu-test.py --image out/aarch64/virt/installed/reference.qcow2 --utm-arguments --audio \
      --home-size dev=64G --default-shell-user dev   # a UTM machine's QEMU arguments (D75)

Standard library only.
"""

import argparse
import base64
import codecs
import json
import os
import platform
import re
import shutil
import signal
import socket
import struct
import subprocess
import zlib
import sys
import tempfile
import threading
import time

FIRMWARE_CODE = {
    "aarch64": [
        "/opt/homebrew/share/qemu/edk2-aarch64-code.fd",
        "/usr/local/share/qemu/edk2-aarch64-code.fd",
        "/usr/share/qemu/edk2-aarch64-code.fd",
        "/usr/share/edk2/aarch64/QEMU_EFI-pflash.raw",
        "/usr/share/AAVMF/AAVMF_CODE.fd",
    ],
    "x86_64": [
        "/opt/homebrew/share/qemu/edk2-x86_64-code.fd",
        "/usr/local/share/qemu/edk2-x86_64-code.fd",
        "/usr/share/qemu/edk2-x86_64-code.fd",
        "/usr/share/edk2/ovmf/OVMF_CODE.fd",
        "/usr/share/OVMF/OVMF_CODE_4M.fd",
        "/usr/share/OVMF/OVMF_CODE.fd",
    ],
}

                                                                                     
FIRMWARE_VARS = {
    "aarch64": [],
    "x86_64": [
        "/opt/homebrew/share/qemu/edk2-i386-vars.fd",
        "/usr/local/share/qemu/edk2-i386-vars.fd",
        "/usr/share/qemu/edk2-i386-vars.fd",
        "/usr/share/edk2/ovmf/OVMF_VARS.fd",
        "/usr/share/OVMF/OVMF_VARS_4M.fd",
        "/usr/share/OVMF/OVMF_VARS.fd",
    ],
}

                                                                                            
                                                                  
SECURE_FIRMWARE_CODE = {
    "aarch64": [
        "/Applications/UTM.app/Contents/Resources/qemu/edk2-aarch64-secure-code.fd",
    ],
    "x86_64": [
        "/opt/homebrew/share/qemu/edk2-x86_64-secure-code.fd",
        "/Applications/UTM.app/Contents/Resources/qemu/edk2-x86_64-secure-code.fd",
        "/usr/share/edk2/ovmf/OVMF_CODE.secboot.fd",
        "/usr/share/OVMF/OVMF_CODE_4M.secboot.fd",
    ],
}

SECURE_FIRMWARE_VARS = {
    "aarch64": ["/Applications/UTM.app/Contents/Resources/qemu/edk2-arm-vars.fd"],
    "x86_64": FIRMWARE_VARS["x86_64"],
}

                                                                                          
                                                                                            
                                                          
FAILURE_PATTERNS = [
    re.compile(r"Kernel panic - not syncing"),
    re.compile(r"You are in emergency mode"),
    re.compile(r"^\[FAILED\] "),
    re.compile(r"^\[DEPEND\] "),
    re.compile(r"Ordering cycle found"),
]

                                                                  
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;:?]*[A-Za-z]")
                                                               
ANSI_PARTIAL = re.compile(r"\x1b(\[[0-9;:?]*)?$")

                                                                                               
                                                                                 
                                                                                       
                                                                               
                                                                                           
                                                    
PASSWORD_HASHES = {
    "dev": "$6$beamline.dev$jzZS2L71jkPcmXY707t/JgYaVU7k5.aklWW9v41mK7QWSPIaN13d./XW.5vPZWYhWt35"
           ".pn2PKzS2dJAd920I0",
    "alice": "$6$beamline.alice$6jP0aHslE7bNkSp3OayK47HO/UIbt9x7.BzT2Bl.M0zWP/b2iC4/aAttUeSLm0Kb6a"
             "31ou35kizzjawy8faS1/",
}


def home_record(name, uid, real_name, groups, size):
    return {
        "userName": name,
        "uid": uid,
        "realName": real_name,
        "disposition": "regular",
        "shell": "/usr/bin/sh",
        "memberOf": groups,
        "storage": "luks",
        "fileSystemType": "btrfs",
        "diskSize": size,
        "enforcePasswordPolicy": False,
        "luksPbkdfType": "argon2id",
        "luksPbkdfMemoryCost": 64 * 1024 * 1024,
        "luksPbkdfTimeCostUSec": 100000,
        "privileged": {"hashedPassword": [PASSWORD_HASHES[name]]},
        "secret": {"password": [name]},
    }


HOMES = {
    "dev": home_record("dev", 60001, "Developer", ["wheel"], 2 * 1024 ** 3),
    "alice": home_record("alice", 60002, "Alice", [], 1024 ** 3),
}


def host_arch():
    machine = platform.machine().lower()
    return {"arm64": "aarch64", "amd64": "x86_64"}.get(machine, machine)


def pick_accel(requested, arch):
    if requested != "auto":
        return requested
    if arch != host_arch():
        return "tcg"
    if sys.platform == "darwin":
        return "hvf"
    if os.access("/dev/kvm", os.R_OK | os.W_OK):
        return "kvm"
    return "tcg"


def find_file(env_var, candidates, what):
    override = os.environ.get(env_var)
    if override:
        if not os.path.exists(override):
            sys.exit(f"qemu-test: {env_var}={override} does not exist")
        return override
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    sys.exit(f"qemu-test: no {what} found; set {env_var}")


def image_format(path):
    with open(path, "rb") as f:
        return "qcow2" if f.read(4) == b"QFI\xfb" else "raw"


def qemu_command(args, accel, workdir, overlay):
    arch = args.arch
    code_candidates = SECURE_FIRMWARE_CODE if args.secure_boot else FIRMWARE_CODE
    vars_candidates = SECURE_FIRMWARE_VARS if args.secure_boot else FIRMWARE_VARS
    code = find_file("QEMU_FIRMWARE_CODE", code_candidates[arch], f"{arch} UEFI firmware")
                                                                                             
                                                                                              
                                                                 
    vars_path = args.vars or (f"{args.persist}.efivars.fd" if args.persist else os.path.join(workdir, "efivars.fd"))
    if not os.path.exists(vars_path):
        if vars_candidates[arch]:
            shutil.copyfile(find_file("QEMU_FIRMWARE_VARS", vars_candidates[arch], f"{arch} UEFI vars"), vars_path)
        else:
            with open(vars_path, "wb") as f:
                f.truncate(os.path.getsize(code))

    cpu = "host" if accel in ("hvf", "kvm") else "max"
    if arch == "aarch64":
        binary, machine = "qemu-system-aarch64", "virt"
    else:
                                                                
        binary, machine = "qemu-system-x86_64", "q35,smm=on" if args.secure_boot else "q35,smm=off"
    binary = args.qemu or os.environ.get("QEMU_SYSTEM") or binary

    cmd = [
        binary,
        "-machine", f"{machine},accel={accel}",
        "-cpu", cpu,
        "-smp", str(args.cpus),
        "-m", args.memory,
        "-drive", f"if=pflash,format=raw,unit=0,readonly=on,file={code}",
        "-drive", f"if=pflash,format={image_format(vars_path)},unit=1,file={vars_path}",
                                                       
        "-drive", f"if=none,id=disk0,format=qcow2,file={overlay}",
        "-device", "virtio-blk-pci,drive=disk0",
        "-netdev", "user,id=net0",
        "-device", "virtio-net-pci,netdev=net0",
        "-device", "virtio-rng-pci",
    ]
    if args.secure_boot and arch == "x86_64":
        cmd += ["-global", "driver=cfi.pflash01,property=secure,value=on"]
    if args.disk:
                                                                                             
        path, _, size = args.disk.partition(":")
        if not os.path.exists(path):
            subprocess.run(["qemu-img", "create", "-q", "-f", "qcow2", path, size or "16G"], check=True)
        cmd += ["-drive", f"if=none,id=disk1,format=qcow2,file={path}",
                "-device", "virtio-blk-pci,drive=disk1,serial=target"]
    if args.tpm:
        tpm_device = "tpm-tis-device" if arch == "aarch64" else "tpm-tis"
        cmd += ["-chardev", f"socket,id=chrtpm,path={os.path.join(workdir, 'swtpm.sock')}",
                "-tpmdev", "emulator,id=tpm0,chardev=chrtpm", "-device", f"{tpm_device},tpmdev=tpm0"]
    if not args.reboot:
                                                                                       
        cmd += ["-no-reboot"]
    if args.gpu != "none":
                                                                                       
                                                                                              
                                                                                             
        gpu = {"2d": "virtio-gpu-pci", "gl": "virtio-gpu-gl-pci",
               "venus": f"virtio-gpu-gl-pci,venus=on,blob=on,hostmem={args.gpu_hostmem}"}[args.gpu]
                                                                                                 
        pointer = "virtio-mouse-pci" if args.pointer == "mouse" else "virtio-tablet-pci"
        cmd += ["-device", gpu, "-device", "virtio-keyboard-pci", "-device", pointer]
    if args.audio:
        backend = "coreaudio" if sys.platform == "darwin" else "pipewire"
        cmd += ["-audiodev", f"{backend},id=snd0", "-device", "virtio-sound-pci,audiodev=snd0"]
    if args.interactive and args.gpu != "none":
                                                                             
        accelerated = args.gpu in ("gl", "venus")
        cmd += ["-display", "sdl,gl=es" if accelerated else "cocoa" if sys.platform == "darwin" else "sdl",
                "-serial", "mon:stdio"]
    elif args.interactive:
                                                                                
        cmd += ["-nographic"]
    else:
        cmd += ["-display", "none", "-monitor", "none", "-serial", "stdio",
                "-qmp", f"unix:{os.path.join(workdir, 'qmp.sock')},server=on,wait=off"]
    for i, spec in enumerate(args.attach_tampered):
        src, mode = spec.rsplit(":", 1)
        copy = tampered_copy(src, mode, workdir, arch)
                                                                       
        cmd += ["-drive", f"if=none,id=tamper{i},format=raw,readonly=on,file={copy}",
                "-device", f"virtio-blk-pci,drive=tamper{i},serial=tamper-{mode}"]
    return cmd + guest_credentials(args)


def parse_size(text):
                                                                           
    match = re.fullmatch(r"(\d+)([KMGT]?)", text)
    if not match:
        sys.exit(f"qemu-test: bad size {text!r}")
    return int(match[1]) * 1024 ** " KMGT".index(match[2] or " ")


def guest_credentials(args):
                                                                                           
                                                                                      
    cmd = []
    sizes = dict(spec.split("=", 1) for spec in args.home_size)
    for name, record in ({} if args.no_homes else HOMES).items():
        record = dict(record)
        if name in args.default_shell_user:
            record.pop("shell")
        if name in sizes:
            record["diskSize"] = parse_size(sizes[name])
        cmd += credential_args(f"home.create.{name}", json.dumps(record))
    for spec in args.credential:
        name, value = spec.split("=", 1)
        cmd += credential_args(name, value)
    for spec in args.credential_file:
        name, path = spec.split("=", 1)
        with open(path, encoding="utf-8") as f:
            cmd += credential_args(name, f.read())
    for path in args.extra_unit:
        with open(path, encoding="utf-8") as f:
            cmd += credential_args(f"systemd.extra-unit.{os.path.basename(path)}", f.read())
                                                                                                
                                                                                                
                                                                                           
                                              
    extra = ["sysctl.kernel.printk_ratelimit=0"]
    extra += [f"systemd.wants={unit}" for unit in args.wants] + args.kernel_arg
    if extra:
                                                                                              
        cmd += ["-smbios", f"type=11,value=io.systemd.stub.kernel-cmdline-extra={' '.join(extra)}"]
    if args.secure_boot:
                                                                                                 
                                                                                                 
                                                                                                 
                                                                                   
        cmd += credential_args("sysctl.extra", "kernel.printk_ratelimit=0\n")
        if args.wants:
            cmd += credential_args("systemd.unit-dropin.beamline-boot-ok.service~beamline-test",
                                   "[Unit]\nWants=" + " ".join(args.wants) + "\n")
    return cmd


def utm_line(arguments):
                                                                                           
                                                                
    if any('"' in a for a in arguments):
        sys.exit('qemu-test: UTM cannot pass an argument containing "')
    return " ".join(f'"{a}"' if any(c.isspace() for c in a) else a for a in arguments)


def utm_arguments(args):
                                                                                              
                                                                                         
                                                               
    cmd = ["-device", "virtio-keyboard-pci", "-device", "virtio-tablet-pci",
           "-device", "virtio-mouse-pci"]
    if args.audio:
        cmd += ["-audiodev", "coreaudio,id=beamline-snd", "-device", "virtio-sound-pci,audiodev=beamline-snd"]
    return cmd + guest_credentials(args)


def qmp(workdir, *commands):
                                                                    
    with socket.socket(socket.AF_UNIX) as s:
        s.connect(os.path.join(workdir, "qmp.sock"))
        f = s.makefile("rw")
        f.readline()                                                        
        for command in ({"execute": "qmp_capabilities"},) + commands:
            f.write(json.dumps(command) + "\n")
            f.flush()
            while True:
                reply = json.loads(f.readline())
                if "event" not in reply:
                    break
            if "error" in reply:
                return reply["error"].get("desc")
    return None


                                                       
QCODES = {**{c: c for c in "abcdefghijklmnopqrstuvwxyz0123456789"},
          " ": "spc", "\n": "ret", "\t": "tab", ".": "dot", "-": "minus", "/": "slash"}


def type_text(workdir, text):
                                                                                           
                                                         
    for token in re.findall(r"\{[a-z]+\}|.", text, re.S):
        if token.startswith("{") and len(token) > 1:
            keys = [{"type": "qcode", "data": token[1:-1]}]
        else:
            keys = [{"type": "qcode", "data": QCODES[token.lower()]}]
            if token.isupper():
                keys.insert(0, {"type": "qcode", "data": "shift"})
        error = qmp(workdir, {"execute": "send-key", "arguments": {"keys": keys, "hold-time": 40}})
        if error:
            print(f"qemu-test: typing failed: {error}", file=sys.stderr)
            return
        time.sleep(0.05)
    print(f"qemu-test: typed {text!r}", file=sys.stderr)


def screendump(workdir, path):
                                                                                    
    error = qmp(workdir, {"execute": "screendump", "arguments": {"filename": os.path.abspath(path)}})
    if error:
        return f"fail: screendump: {error}"
    with open(path, "rb") as img:
        data = img.read()
                                                                       
    header = data.split(b"\n", 3)
    if len(header) < 4 or header[0] != b"P6":
        return "fail: screendump is not a binary PPM"
    pixels = header[3]
    colours = {pixels[i:i + 3] for i in range(0, len(pixels) - 2, 3 * 97)}
    if len(colours) < 8:
        return f"fail: screendump {path} is blank ({len(colours)} colours)"
    print(f"qemu-test: screendump {path} ({header[1].decode()}, {len(colours)}+ colours)", file=sys.stderr)
    return "pass"


def credential_args(name, value):
                                                                  
    encoded = base64.b64encode(value.encode()).decode()
    return ["-smbios", f"type=11,value=io.systemd.credential.binary:{name}={encoded}"]


def start_swtpm(state, workdir):
                                                                                            
    os.makedirs(state, mode=0o700, exist_ok=True)
    pidfile = os.path.join(workdir, "swtpm.pid")
    subprocess.run(["swtpm", "socket", "--tpm2", "--tpmstate", f"dir={os.path.abspath(state)},mode=0600",
                    "--ctrl", f"type=unixio,path={os.path.join(workdir, 'swtpm.sock')},mode=0600,terminate",
                    "--flags", "not-need-init", "--daemon", "--pid", f"file={pidfile}"], check=True)
    return pidfile


def stop_swtpm(pidfile):
    try:
        with open(pidfile, encoding="utf-8") as f:
            os.kill(int(f.read().strip()), 15)
    except (OSError, ValueError):
        pass


def create_overlay(image, workdir, size, path=None):
    overlay = path or os.path.join(workdir, "overlay.qcow2")
    cmd = ["qemu-img", "create", "-q", "-f", "qcow2", "-F", image_format(image), "-b", os.path.abspath(image), overlay]
    if size:
        cmd.append(size)
    subprocess.run(cmd, check=True)
    return overlay


def persistent_overlay(image, path, size):
                                                                                                 
                                                                                                   
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        print(f"qemu-test: creating persistent overlay {path} ({size})", file=sys.stderr)
        return create_overlay(image, None, size, path)
    info = json.loads(subprocess.run(["qemu-img", "info", "--output=json", "-U", path],
                                     check=True, capture_output=True, text=True).stdout)
    backing = info.get("full-backing-filename") or info.get("backing-filename")
    if not backing or os.path.realpath(backing) != os.path.realpath(image):
        sys.exit(f"qemu-test: {path} is backed by {backing}, not {image}; "
                 "use that image, or remove the overlay (and its .efivars.fd) to start afresh")
    return path


                                                                                      
ROOT_TYPE = {"aarch64": "b921b045-1df0-41c3-af44-4c6f280d3fae",
             "x86_64": "4f68bce3-e8cd-4db1-96e7-fbcaf984b709"}


LINUX_GENERIC_TYPE = "0fc63daf-8483-4772-8e79-3d69d8477de4"


def guid_to_str(raw):
    a, b, c = struct.unpack_from("<IHH", raw, 0)
    return f"{a:08x}-{b:04x}-{c:04x}-{raw[8:10].hex()}-{raw[10:16].hex()}"


def str_to_guid(text):
    h = text.replace("-", "")
    return struct.pack("<IHH", int(h[0:8], 16), int(h[8:12], 16), int(h[12:16], 16)) + bytes.fromhex(h[16:])


def gpt_entries(image):
                                                                                            
                            
    with open(image, "rb") as f:
        f.seek(512)
        header = f.read(512)
        if header[:8] != b"EFI PART":
            sys.exit(f"qemu-test: {image} has no GPT")
        entries_lba, count, entry_size = struct.unpack_from("<QII", header, 72)
        f.seek(entries_lba * 512)
        table = f.read(count * entry_size)
    parts = []
    for i in range(count):
        entry = table[i * entry_size:(i + 1) * entry_size]
        if entry[:16] == bytes(16):
            continue
        first, last = struct.unpack_from("<QQ", entry, 32)
        parts.append({"entry": entries_lba * 512 + i * entry_size, "type": guid_to_str(entry[:16]),
                      "label": entry[56:128].decode("utf-16-le").rstrip("\0"),
                      "offset": first * 512, "size": (last - first + 1) * 512})
    return header, entries_lba, count, entry_size, parts


def gpt_partition(image, wanted, arch):
                                                                                              
                                                
    for part in gpt_entries(image)[4]:
        if part["label"] == wanted or (wanted == "root" and part["type"] == ROOT_TYPE[arch]):
            return part["offset"]
    sys.exit(f"qemu-test: no partition {wanted} in {image}")


def tampered_copy(src, mode, workdir, arch):
                                                                                 
                                                                                    
                                                                   
                                                                                             
    dest = os.path.join(workdir, f"tampered-{mode}.raw")
    shutil.copyfile(src, dest)
    header, entries_lba, count, entry_size, parts = gpt_entries(dest)
    data = next(p for p in parts if p["type"] == ROOT_TYPE[arch])
    sig = next(p for p in parts if p["label"].endswith("-verity-sig"))
    with open(dest, "r+b") as f:
        if mode == "data":
            f.seek(data["offset"])
            f.write(b"\x5a" * 4096)
        elif mode == "signature":
            f.seek(sig["offset"])
            blob = f.read(sig["size"])
            at = blob.index(b'"signature":"') + len(b'"signature":"') + 16
            f.seek(sig["offset"] + at)
            f.write(b"B" if blob[at:at + 1] == b"A" else b"A")
        elif mode == "unsigned":
            f.seek(sig["entry"])
            f.write(str_to_guid(LINUX_GENERIC_TYPE))
            f.seek(entries_lba * 512)
            table = f.read(count * entry_size)
            header = bytearray(header[:struct.unpack_from("<I", header, 12)[0]])
            struct.pack_into("<I", header, 88, zlib.crc32(table))
            struct.pack_into("<I", header, 16, 0)
            struct.pack_into("<I", header, 16, zlib.crc32(header))
            f.seek(512)
            f.write(header)
        else:
            sys.exit(f"qemu-test: unknown tamper mode {mode}")
    return dest


def raw_view(image, workdir):
                                                                                             
                                                                                            
    if image_format(image) == "raw":
        return image
    raw = os.path.join(workdir, "raw-view.raw")
    if not os.path.exists(raw):
        subprocess.run(["qemu-img", "convert", "-f", image_format(image), "-O", "raw", image, raw], check=True)
    return raw


def tamper(image, overlay, label, arch, workdir):
                                                                                                  
    offset = gpt_partition(raw_view(image, workdir), label, arch)
    subprocess.run(["qemu-io", "-f", "qcow2", "-c", f"write -P 0x5a {offset} 4096", overlay],
                   check=True, stdout=subprocess.DEVNULL)
    print(f"qemu-test: tampered with {label} at byte {offset} (overlay only)", file=sys.stderr)


def tamper_file(image, overlay, spec, workdir):
                                                                                                 
                                                                                                  
                                                                                                    
                                        
    label, path = spec.split(":", 1)
    raw = raw_view(image, workdir)
    part = next((p for p in gpt_entries(raw)[4] if p["label"] == label), None)
    if not part:
        sys.exit(f"qemu-test: no partition {label} in {image}")
    with open(path, "rb") as f:
        content = f.read()
    at = (len(content) // 2) & ~0xFFF
    block = content[at:at + 4096]
    with open(raw, "rb") as f:
        f.seek(part["offset"])
        data = f.read(part["size"])
    offsets, found = [], data.find(block)
    while found >= 0:
        offsets.append(part["offset"] + found)
        found = data.find(block, found + 1)
    if not offsets:
        sys.exit(f"qemu-test: {os.path.basename(path)} is not on {label}")
    for offset in offsets:
        subprocess.run(["qemu-io", "-f", "qcow2", "-c", f"write -P {block[0] ^ 0xFF} {offset} 1", overlay],
                       check=True, stdout=subprocess.DEVNULL)
    print(f"qemu-test: tampered with {os.path.basename(path)}'s middle block, found {len(offsets)} times on "
          f"{label} (overlay only)", file=sys.stderr)


CONSOLE_SETTLE = 2.0                                                     


def run_test(cmd, args, workdir=None):
    log = open(args.log, "w", encoding="utf-8") if args.log else None
    expect = re.compile(args.expect)
    fail_on = [re.compile(p) for p in args.fail_on]
                                                                                         
    typing = []
    for spec in args.type:
        pattern, delay, text = spec.split("::", 2)
        typing.append([re.compile(pattern), float(delay), text.replace("\\n", "\n"), False])
    required = {pattern: re.compile(pattern) for pattern in args.require}
    seen = set()
    result = {"status": None}
    script = load_serial_script(args.serial_script) if args.serial_script else []
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE if script else subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                                                                                             
                                                                                          
                                                                                                
                                                                                       
    stream = {"text": "", "partial": "", "decoder": codecs.getincrementaldecoder("utf-8")(errors="replace")}

    def advance_script(chunk):
        text = stream["partial"] + stream["decoder"].decode(chunk)
        partial = ANSI_PARTIAL.search(text)
        stream["partial"] = partial.group(0) if partial else ""
        if partial:
            text = text[:partial.start()]
        stream["text"] = (stream["text"] + ANSI_ESCAPE.sub("", text))[-8192:]
        while script:
            kind, value = script[0]
            if kind == "sleep":
                                                                                 
                                                                                
                time.sleep(value)
                script.pop(0)
                continue
            if kind == "send":
                proc.stdin.write(value.encode())
                proc.stdin.flush()
                script.pop(0)
                continue
            if kind == "choose":
                choice = menu_choice(stream["text"], value)
                if choice is None:
                    break
                index, end = choice
                stream["text"] = stream["text"][end:]
                                                                                               
                script[0:1] = [("sleep", 1)] + [("send", SERIAL_KEYS["{down}"]), ("sleep", 1)] * index + \
                    [("send", SERIAL_KEYS["{enter}"])]
                continue
            match = value.search(stream["text"])
            if not match:
                break
            stream["text"] = stream["text"][match.end():]
            script.pop(0)

    def lines():
                                                                                        
        pending = b""
        while True:
            chunk = os.read(proc.stdout.fileno(), 4096)
            if not chunk:
                break
            if script:
                advance_script(chunk)
            pending += chunk
            *complete, pending = pending.split(b"\n")
            for raw in complete:
                yield raw + b"\n"
        if pending:
            yield pending

    def reader():
        for raw in lines():
            line = raw.decode("utf-8", errors="replace")
            sys.stdout.write(line)
            sys.stdout.flush()
            if log:
                log.write(line)
            plain = ANSI_ESCAPE.sub("", line).strip()
            seen.update(name for name, p in required.items() if p.search(plain))
            for step in typing:
                if not step[3] and workdir and step[0].search(plain):
                    step[3] = True
                    threading.Timer(step[1], type_text, (workdir, step[2])).start()
            if result["status"] is None:
                if expect.search(plain) and not script:
                    missing = sorted(set(required) - seen)
                    result["status"] = f"fail: '{args.expect}' before {', '.join(missing)}" if missing else "pass"
                elif any(p.search(plain) for p in fail_on) or (
                        not (args.tamper or args.allow_failures) and any(p.search(plain) for p in FAILURE_PATTERNS)):
                    result["status"] = "fail: " + plain

                                                                                             
    signal.signal(signal.SIGTERM, lambda *_: result.update(status="fail: terminated"))
    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    deadline = time.monotonic() + args.timeout
    while result["status"] is None and proc.poll() is None and time.monotonic() < deadline:
        time.sleep(0.2)
    if result["status"] == "pass" and args.screendump and workdir:
        time.sleep(args.screendump_delay)
        result["status"] = screendump(workdir, args.screendump)

                                                                                            
                                                                                         
    if result["status"] is not None and proc.poll() is None:
        time.sleep(CONSOLE_SETTLE)
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    thread.join(timeout=5)
    if log:
        log.close()

    status = result["status"]
    if status is None:
        status = f"fail: QEMU exited with {proc.returncode}" if time.monotonic() < deadline else \
            f"fail: no '{args.expect}' within {args.timeout}s"
    return status


                                                                                               
                                                
SERIAL_KEYS = {"{enter}": "\r", "{up}": "\x1b[A", "{down}": "\x1b[B", "{right}": "\x1b[C",
               "{left}": "\x1b[D", "{esc}": "\x1b"}


                                                                                              
                                                      
MENU_BOX = re.compile(r"/-{3,}\\((?:\s*\|[^|]*\|)+)\s*\\-{3,}/")


def menu_choice(text, pattern):
                                                                                              
                                                                               
    choice = None
    for box in MENU_BOX.finditer(text):
        items = [item.strip() for item in re.findall(r"\|([^|]*)\|", box.group(1))]
        for index, item in enumerate(items):
            if pattern.fullmatch(item):
                choice = (index, box.end())
                break
    return choice


def load_serial_script(path):
                                                                                            
                                                                                                    
                                                                                                  
                     
    steps = []
    with open(path, encoding="utf-8") as f:
        for number, line in enumerate(f, 1):
            line = line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            kind, _, value = line.partition(" ")
            if kind == "expect":
                steps.append(("expect", re.compile(value)))
            elif kind == "choose":
                steps.append(("choose", re.compile(value)))
            elif kind == "send":
                value = value.replace("\\n", "\n")
                for name, keys in SERIAL_KEYS.items():
                    value = value.replace(name, keys)
                steps.append(("send", value))
            elif kind == "sleep":
                try:
                    seconds = float(value)
                    if not 0 <= seconds <= 10:
                        raise ValueError
                except ValueError:
                    sys.exit(f"qemu-test: {path}:{number}: sleep must be 0..10 seconds")
                steps.append(("sleep", seconds))
            else:
                sys.exit(f"qemu-test: {path}:{number}: expected `expect`, `send`, `choose` or `sleep`")
    return steps


def main():
    parser = argparse.ArgumentParser(description=HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--image", required=True, help="raw disk image (never modified)")
    parser.add_argument("--arch", default=host_arch(), choices=sorted(FIRMWARE_CODE))
    parser.add_argument("--accel", default=os.environ.get("QEMU_ACCEL", "auto"),
                        choices=["auto", "hvf", "kvm", "tcg"])
    parser.add_argument("--expect", default="BEAMLINE_BOOT_OK", help="regex that marks success on the serial console")
    parser.add_argument("--require", action="append", default=[], metavar="REGEX",
                        help="regex that must appear before --expect (repeatable)")
    parser.add_argument("--extra-unit", action="append", default=[], metavar="FILE",
                        help="unit file to inject as a systemd.extra-unit credential (repeatable)")
    parser.add_argument("--wants", action="append", default=[], metavar="UNIT",
                        help="unit to pull in through the kernel command line (repeatable)")
    parser.add_argument("--kernel-arg", action="append", default=[], metavar="ARG",
                        help="extra kernel command line argument (repeatable)")
    parser.add_argument("--gpu", choices=["none", "2d", "gl", "venus"], default="none",
                        help="virtual GPU: 2d virtio-gpu (software rendering), gl virgl, venus virgl plus "
                             "Vulkan (gl and venus need a QEMU built with virglrenderer)")
    parser.add_argument("--gpu-hostmem", default="4G",
                        help="host memory window for Venus' blob resources (--gpu venus)")
    parser.add_argument("--pointer", choices=["tablet", "mouse"], default="tablet",
                        help="absolute tablet, or a relative mouse for games (grab the window first)")
    parser.add_argument("--audio", action="store_true",
                        help="virtio-sound through the host (CoreAudio on macOS, PipeWire on Linux)")
    parser.add_argument("--utm-arguments", action="store_true",
                        help="print the extra QEMU arguments for a UTM machine as one line for a single "
                             "UTM argument field, instead of booting (input devices, --audio, accounts, "
                             "credentials, units)")
    parser.add_argument("--persist", metavar="OVERLAY",
                        help="boot a persistent overlay (created on first use with --disk-size) and keep "
                             "its UEFI variables in OVERLAY.efivars.fd; the image is never written")
    parser.add_argument("--qemu", help="QEMU system emulator binary (default from PATH, or QEMU_SYSTEM)")
    parser.add_argument("--serial-script", metavar="FILE",
                        help="drive the serial console: `expect REGEX` / `send TEXT` lines; --expect "
                             "only counts once the script has finished")
    parser.add_argument("--type", action="append", default=[], metavar="REGEX::SECONDS::TEXT",
                        help="once REGEX appears on the console, type TEXT on the virtual keyboard after "
                             "SECONDS (named keys as {down}, {ret}, ...; repeatable; needs --gpu)")
    parser.add_argument("--screendump", metavar="PPM",
                        help="after --expect, capture the display here and fail if it is blank")
    parser.add_argument("--screendump-delay", type=float, default=5.0,
                        help="seconds to wait before the capture (default 5)")
    parser.add_argument("--timeout", type=int, default=None, help="seconds (default 300, 1200 under TCG)")
    parser.add_argument("--tamper", metavar="LABEL",
                        help="corrupt the first block of the GPT partition with this label (or `root`: the "
                             "first root partition, SYSTEM-A) in the overlay; the boot is expected to fail, so "
                             "failed units do not end the test (--expect names the failure)")
    parser.add_argument("--tamper-file", metavar="LABEL:FILE",
                        help="change one byte of FILE's middle 4 KiB block wherever it occurs on the GPT partition "
                             "LABEL, in the overlay (UKIs the firmware must then refuse)")
    parser.add_argument("--credential", action="append", default=[], metavar="NAME=VALUE",
                        help="pass a system credential (repeatable)")
    parser.add_argument("--credential-file", action="append", default=[], metavar="NAME=FILE",
                        help="pass a file's contents as a system credential (repeatable)")
    parser.add_argument("--default-shell-user", action="append", default=[], choices=sorted(HOMES),
                        help="omit this test user's shell to exercise homed's built-in default")
    parser.add_argument("--no-homes", action="store_true",
                        help="pass no home.create credentials: the first boot asks for an account on the "
                             "console (an installed system, D112)")
    parser.add_argument("--home-size", action="append", default=[], metavar="USER=SIZE",
                        help="create this test user's LUKS home with SIZE (e.g. dev=64G) instead of the "
                             "test default")
    parser.add_argument("--allow-failures", action="store_true",
                        help="failed units do not end the test (tests that make boots fail on purpose)")
    parser.add_argument("--fail-on", action="append", default=[], metavar="REGEX",
                        help="a console line that fails the test at once, even with --allow-failures (repeatable)")
    parser.add_argument("--attach-tampered", action="append", default=[], metavar="IMAGE:MODE",
                        help="attach a tampered copy of an extension image (MODE: signature, data, "
                             "unsigned) as /dev/disk/by-id/virtio-tamper-MODE (repeatable)")
    parser.add_argument("--reboot", action="store_true",
                        help="let the guest reboot (same overlay, same credentials) instead of ending QEMU")
    parser.add_argument("--secure-boot", action="store_true",
                        help="Secure Boot capable firmware; fresh vars start in setup mode (no keys)")
    parser.add_argument("--vars", metavar="FILE",
                        help="UEFI variables kept in FILE across runs (created from the template on first use)")
    parser.add_argument("--tpm", metavar="DIR",
                        help="attach a TPM 2.0 (swtpm), its state kept in DIR across runs")
    parser.add_argument("--disk", metavar="FILE[:SIZE]",
                        help="attach a second disk (qcow2, created blank with SIZE, default 16G, if missing)")
    parser.add_argument("--memory", default="2G")
    parser.add_argument("--cpus", type=int, default=4)
    parser.add_argument("--disk-size", default="16G",
                        help="virtual size of the overlay; DATA grows into it at first boot")
    parser.add_argument("--log", help="also write the serial console to this file")
    parser.add_argument("--interactive", action="store_true",
                        help="attach the serial console to this terminal; dev/dev or alice/alice can log in (Ctrl-a x quits)")
    args = parser.parse_args()

    if args.utm_arguments:
        print(utm_line(utm_arguments(args)))
        return 0
    if not os.path.isfile(args.image):
        sys.exit(f"qemu-test: image {args.image} not found")
    accel = pick_accel(args.accel, args.arch)
    if args.timeout is None:
        args.timeout = 1200 if accel == "tcg" else 300

    if args.persist and (args.tamper or args.tamper_file or args.attach_tampered):
        sys.exit("qemu-test: --persist cannot be combined with tampering, which belongs to throwaway tests")
    with tempfile.TemporaryDirectory(prefix="beamline-qemu-") as workdir:
        if args.persist:
            overlay = persistent_overlay(args.image, args.persist, args.disk_size)
        else:
            overlay = create_overlay(args.image, workdir, args.disk_size)
        if args.tamper:
            tamper(args.image, overlay, args.tamper, args.arch, workdir)
        if args.tamper_file:
            tamper_file(args.image, overlay, args.tamper_file, workdir)
        cmd = qemu_command(args, accel, workdir, overlay)
        print(f"qemu-test: accel={accel} arch={args.arch} image={args.image}", file=sys.stderr)
        swtpm = start_swtpm(args.tpm, workdir) if args.tpm else None
        try:
            if args.interactive:
                return subprocess.call(cmd)
            status = run_test(cmd, args, workdir)
        finally:
            if swtpm:
                stop_swtpm(swtpm)

    print(f"qemu-test: {status}", file=sys.stderr)
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
