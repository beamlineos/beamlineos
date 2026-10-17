# SPDX-License-Identifier: MIT
# shellcheck shell=sh








provision_vars() {
    rm -f "$1"
    python3 "$REPO/tools/qemu-test.py" --arch "$ARCH" --image "$OUT/firmware/provision.raw" \
        --secure-boot --vars "$1" \
        --expect 'Custom Secure Boot keys successfully enrolled' --timeout 120 --log "$2"
}





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




serve_channel() {
    port="$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')"
    python3 -m http.server --bind 127.0.0.1 --directory "$1" "$port" >"$DIR_WORK/http.log" 2>&1 &
    # shellcheck disable=SC2034 # the caller kills $server when it is done
    server=$!
    python3 "$REPO/tools/update_transfers.py" render "$REPO/files/base/sysupdate.d" \
        "http://10.0.2.2:$port/" > "$DIR_WORK/tmpfiles.extra"
}





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
