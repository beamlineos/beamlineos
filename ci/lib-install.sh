# SPDX-License-Identifier: MIT
# shellcheck shell=sh
#
# Installing a disk from a medium, shared by ci/test-install and ci/test-update (docs/decisions.md
# D113). Sourced after ci/lib.sh; the caller sets DIR_WORK to its temporary directory. A machine
# directory holds what an installed disk needs between runs: target.qcow2 (the disk), efivars.fd
# (its UEFI variables) and tpm/ (its TPM's state).

# provision_vars VARS LOG: UEFI variables holding Microsoft's keys, as a PC is sold. The
# provisioning disk's systemd-boot enrolls them in setup mode and reboots.
provision_vars() {
    rm -f "$1"
    python3 "$REPO/tools/qemu-test.py" --arch "$ARCH" --image "$OUT/firmware/provision.raw" \
        --secure-boot --vars "$1" \
        --expect 'Custom Secure Boot keys successfully enrolled' --timeout 120 --log "$2"
}

# install_medium MEDIUM DIR secure-boot|plain LOG: install MEDIUM to a blank DIR/target.qcow2,
# answering the prompts on the console. With secure-boot, DIR/efivars.fd must hold Microsoft's
# keys: MokManager enrolls Beamline's key first, then sysinstall runs, with the TPM in DIR/tpm.
# plain uses firmware without Secure Boot, for media that predate the shim chain.
install_medium() {
    script="$DIR_WORK/install-$(basename "$2").script"
    if [ "$3" = secure-boot ]; then
        cat "$REPO/tests/vm/mok-enroll.script" "$REPO/tests/vm/install.script" > "$script"
        firmware="--secure-boot"
    else
        cat "$REPO/tests/vm/install.script" > "$script"
        firmware=""
    fi
    # shellcheck disable=SC2086 # $firmware is one optional argument
    python3 "$REPO/tools/qemu-test.py" --arch "$ARCH" --image "$1" $firmware \
        --vars "$2/efivars.fd" --tpm "$2/tpm" --reboot \
        --disk "$2/target.qcow2:16G" \
        --extra-unit "$REPO/tests/vm/beamline-selinux-mode.service" \
        --wants beamline-selinux-mode.service \
        --require BEAMLINE_SELINUX_OK --require 'BEAMLINE_SELINUX_ENFORCE=1' \
        --serial-script "$script" \
        --expect 'reboot: Restarting system' --timeout 900 \
        --log "$4"
}

# serve_channel DIR: serve an update channel over HTTP on this host, and write the transfer
# definitions pointed at it (QEMU's user network reaches the host as 10.0.2.2) as a tmpfiles.extra
# credential, $DIR_WORK/tmpfiles.extra, that writes them to /run/sysupdate.d. Sets $server.
serve_channel() {
    port="$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')"
    python3 -m http.server --bind 127.0.0.1 --directory "$1" "$port" >"$DIR_WORK/http.log" 2>&1 &
    # shellcheck disable=SC2034 # the caller kills $server when it is done
    server=$!
    python3 - "$REPO/files/base/sysupdate.d" "http://10.0.2.2:$port/" > "$DIR_WORK/tmpfiles.extra" <<'EOF'
import os, sys
src, url = sys.argv[1:]
for name in sorted(os.listdir(src)):
    lines = [f"Path={url}\n" if line.startswith("Path=https://") else line
             for line in open(os.path.join(src, name)) if not line.startswith("#")]
    body = "".join(lines).replace("\\", "\\\\").replace("\n", "\\n").replace("%", "%%")
    print(f"f+ /run/sysupdate.d/{name} 0644 - - - {body}")
EOF
}

# prepare_reference DIR secure-boot|plain LOG: DIR/reference.qcow2, a persistent overlay of
# DIR/target.qcow2 after its first boot (the test accounts from their credentials, the extensions
# fetched from the served channel, the reboot), powered off cleanly after its second boot. Uses
# DIR/efivars.fd and DIR/tpm, which it changes; copy them first for other runs.
prepare_reference() {
    if [ "$2" = secure-boot ]; then firmware="--secure-boot"; else firmware=""; fi
    rm -f "$1/reference.qcow2"
    # shellcheck disable=SC2086 # $firmware is one optional argument
    python3 "$REPO/tools/qemu-test.py" --arch "$ARCH" --image "$1/target.qcow2" $firmware \
        --persist "$1/reference.qcow2" --vars "$1/efivars.fd" --tpm "$1/tpm" --reboot \
        --credential-file "tmpfiles.extra=$DIR_WORK/tmpfiles.extra" \
        --extra-unit "$REPO/tests/vm/beamline-poweroff.service" \
        --wants beamline-poweroff.service \
        --require 'Detected first boot' --require BEAMLINE_BOOT_OK \
        --expect 'reboot: Power down' --timeout 600 \
        --log "$3"
}
