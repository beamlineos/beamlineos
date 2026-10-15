# SPDX-License-Identifier: MIT
# VM-only harness: shell orchestration is never shipped in an image.
set -eu
failure() {
    journalctl -b --no-pager -n 100 -u beamline-extensions-refresh.service -u beamline-printing-start.service || :
    echo BEAMLINE_CTL_FAILED
}
trap failure EXIT
systemctl start beamlinectld.socket
systemd-tmpfiles --create --inline 'd /run/beamline-test-ctl 0755 - - -'
systemd-tmpfiles --create --inline 'd /var/lib/beamline-test 0755 root root -'
stage=0
if [ -e /var/lib/beamline-test/ctl-stage ]; then read -r stage < /var/lib/beamline-test/ctl-stage; fi
state_is() {
    wanted=$1 saved=$2 merged=$3
    beamlinectl list > /run/beamline-test-ctl/list
    while read -r name enabled active available _live; do
        [ "$name" = "$wanted" ] || continue
        [ "$enabled" = "$saved" ] && [ "$active" = "$merged" ] && [ "$available" = yes ]
        return $?
    done < /run/beamline-test-ctl/list
    return 1
}
await_marker() {
    attempt=0
    while [ "$attempt" -lt 180 ]; do
        [ ! -e "$1" ] || return 0
        udevadm wait --timeout=1 /dev/beamline-ctl-never 2>/dev/null || :
        attempt=$((attempt + 1))
    done
    return 1
}
reboot_to() {
    printf '%s\n' "$1" > /var/lib/beamline-test/ctl-stage
    trap - EXIT
    systemctl --no-block reboot
    exit 0
}

# Observe the actual kernel labels while a real client holds an activated connection.
if [ "$stage" = 0 ]; then
varlinkctl introspect /run/varlink/registry/org.beamline.Extensions
state_is desktop-gnome yes yes
state_is posix no no
echo BEAMLINE_CTL_DEFAULTS_OK
observe() {
    : > /run/beamline-test-ctl/observer-ready
    while [ ! -e /run/beamline-test-ctl/calls-done ]; do
        for process in /proc/[0-9]*; do
            command='' context=''
            { read -r command < "$process/comm"; } 2>/dev/null || :
            case "$command" in beamlinectl|beamlinectld) ;; *) continue ;; esac
            { read -r context < "$process/attr/current"; } 2>/dev/null || :
            case "$command:$context" in
                beamlinectld:system_u:system_r:beamlinectl_t:s3:c0.c1023*)
                    : > /run/beamline-test-ctl/daemon ;;
                beamlinectl:user_u:user_r:user_t:s0:c0*)
                    : > /run/beamline-test-ctl/client ;;
                *) echo "unexpected $command context: $context"; return 1 ;;
            esac
        done
        [ ! -e /run/beamline-test-ctl/daemon ] || [ ! -e /run/beamline-test-ctl/client ] || return 0
    done
}
observe & observer=$!
while [ ! -e /run/beamline-test-ctl/observer-ready ]; do :; done
for user in alice dev; do
    for _round in 1 2 3 4 5; do
        out=$(systemd-run --quiet --wait --pipe --collect --property="User=$user" \
            --property=SELinuxContext=user_u:user_r:user_t:s0:c0 /usr/bin/beamlinectl --json list)
        case "$out" in *'"name":"posix"'*'"name":"posix-devel"'*'"name":"printing-scanning"'*) ;; *) echo "$out"; exit 1 ;; esac
    done
done
echo BEAMLINE_CTL_READY_0
await_marker /var/lib/beamline/state/posix.enabled
await_marker /tmp/beamline-ctl-confirm-0
# The real password prompt holds both processes live, so observing their labels does not
# depend on catching a short List call between two /proc scans on a busy host.
: > /run/beamline-test-ctl/calls-done
wait "$observer"
[ -e /run/beamline-test-ctl/daemon ]
echo BEAMLINE_CTL_DAEMON_CONTEXT_OK
[ -e /run/beamline-test-ctl/client ]
echo BEAMLINE_CTL_CLIENT_CONTEXT_OK
state_is posix yes no
reboot_to 1
elif [ "$stage" = 1 ]; then
    state_is desktop-gnome yes yes
    state_is posix yes yes
    for unit in beamline-extension@.service beamline-extension-unlink@.service beamline-extensions-refresh.service; do
        label=$(getfilecon "/usr/lib/systemd/system/$unit")
        case "$label" in *:beamline_extension_unit_t:s3:c0.c1023*) ;; *) echo "wrong $unit label: $label"; exit 1 ;; esac
    done
    echo BEAMLINE_CTL_UNIT_LABELS_OK
    echo BEAMLINE_CTL_POSIX_BOOT_OK
    echo BEAMLINE_CTL_READY_1
    await_marker /var/lib/beamline/state/desktop-gnome.disabled
    await_marker /tmp/beamline-ctl-confirm-1
    state_is desktop-gnome no yes
    reboot_to 2
elif [ "$stage" = 2 ]; then
    state_is desktop-gnome no no
    state_is posix yes yes
    [ ! -e /usr/bin/gnome-shell ]
    if systemctl is-active --quiet display-manager.service; then exit 1; fi
    echo BEAMLINE_CTL_DESKTOP_OFF_OK
    # P0 uses the marker's owning UID so DAC cannot be the refusal. P2 root may bypass DAC.
    if systemd-run --quiet --wait --pipe --collect --property=User=beamline-ctl \
        --property=SELinuxContext=user_u:user_r:user_t:s0:c0 \
        /usr/bin/sh -c 'printf bad >> /var/lib/beamline/state/posix.enabled'; then exit 1; fi
    if systemd-run --quiet --wait --pipe --collect --property=User=root \
        --property=SELinuxContext=admin_u:admin_r:admin_t:s2:c0.c1023 \
        /usr/bin/sh -c 'printf bad >> /var/lib/beamline/state/posix.enabled'; then exit 1; fi
    state_is posix yes yes
    echo BEAMLINE_CTL_STATE_PROTECTED_OK
    echo BEAMLINE_CTL_READY_2
    await_marker /tmp/beamline-ctl-users-done
    state_is desktop-gnome no no
    state_is posix yes yes
    fail_with() {
        error=$1; shift
        if "$@" > /run/beamline-test-ctl/error 2>&1; then echo "unexpected success: $*"; exit 1; fi
        grep -F "$error" /run/beamline-test-ctl/error
    }
    fail_with NotLive beamlinectl activate desktop-gnome
    fail_with NotLive beamlinectl deactivate desktop-gnome
    fail_with WouldLeaveNoInteractiveEnvironment beamlinectl deactivate posix
    beamlinectl enable desktop-gnome
    state_is desktop-gnome yes no
    # Both guards must run BEFORE changing a saved choice. Desktop is saved, but not active.
    fail_with WouldLeaveNoInteractiveEnvironment beamlinectl disable --now posix
    state_is posix yes yes
    fail_with WouldLeaveNoInteractiveEnvironment beamlinectl deactivate posix
    echo BEAMLINE_CTL_LIVE_GUARD_OK

    # A refresh must not apply a choice saved for next boot, or bring up the desktop live.
    beamlinectl enable posix-devel
    state_is posix-devel yes no
    beamlinectl activate printing-scanning
    state_is printing-scanning no yes
    state_is posix-devel yes no
    state_is desktop-gnome yes no
    lpstat -r
    systemctl is-active --quiet cups.service
    beamlinectl deactivate printing-scanning
    state_is printing-scanning no no
    if systemctl is-active --quiet cups.service; then exit 1; fi
    if systemctl is-active --quiet cups.socket; then exit 1; fi
    if systemctl is-active --quiet cups.path; then exit 1; fi
    [ ! -e /usr/bin/lpstat ]
    beamlinectl deactivate printing-scanning
    state_is printing-scanning no no
    echo BEAMLINE_CTL_PRINTING_STOP_OK
    beamlinectl disable posix-devel

    # Failure after durable save: a malformed runtime marker exercises real filesystem failure
    # without leaving a failed service or introducing a security-policy exception.
    systemd-tmpfiles --create --inline 'f+ /run/beamline/active/posix-devel 0644 beamline-ctl beamline-ctl - invalid'
    fail_with OperationFailed beamlinectl --json enable posix-devel --now
    grep -F '"stage":"mark-active"' /run/beamline-test-ctl/error
    grep -F '"enabled":true' /run/beamline-test-ctl/error
    grep -F '"active":false' /run/beamline-test-ctl/error
    grep -F '"rebootRequired":true' /run/beamline-test-ctl/error
    state_is posix-devel yes no
    systemd-tmpfiles --remove --inline 'r /run/beamline/active/posix-devel'
    beamlinectl activate posix-devel
    state_is posix-devel yes yes
    beamlinectl disable posix-devel --now
    state_is posix-devel no no
    echo BEAMLINE_CTL_FAILURE_POLICY_OK

    # Saved desktop enablement is insufficient if either current image is absent.
    # shellcheck source=/dev/null
    . /usr/lib/os-release
    image=/var/lib/beamline/confexts/desktop-gnome_$IMAGE_VERSION.raw
    mv "$image" "$image.test-hidden"
    fail_with WouldLeaveNoInteractiveEnvironment beamlinectl disable posix
    state_is posix yes yes
    mv "$image.test-hidden" "$image"
    image=/var/lib/beamline/confexts/posix-devel_$IMAGE_VERSION.raw
    mv "$image" "$image.test-hidden"
    fail_with ImageMissing beamlinectl enable posix-devel
    beamlinectl list > /run/beamline-test-ctl/list
    grep '^posix-devel *no *no *no' /run/beamline-test-ctl/list
    mv "$image.test-hidden" "$image"
    echo BEAMLINE_CTL_MISSING_IMAGES_OK

    # Two concurrent removals must serialize and leave exactly one interactive saved choice.
    beamlinectl disable desktop-gnome > /run/beamline-test-ctl/race-desktop 2>&1 & first=$!
    beamlinectl disable posix > /run/beamline-test-ctl/race-posix 2>&1 & second=$!
    a=0; wait "$first" || a=$?
    b=0; wait "$second" || b=$?
    case "$a:$b" in 0:1|1:0) ;; *) echo "bad concurrent results: $a:$b"; exit 1 ;; esac
    beamlinectl enable desktop-gnome
    beamlinectl enable posix
    state_is desktop-gnome yes no
    state_is posix yes yes
    echo BEAMLINE_CTL_CONCURRENT_GUARD_OK
    reboot_to 3
elif [ "$stage" = 3 ]; then
    state_is desktop-gnome yes yes
    state_is posix yes yes
    beamlinectl deactivate posix
    state_is posix yes no
    # Reproduce stale links from a failed cleanup after the instance has become inactive.
    # A retry must remove them even though StopUnit itself has no ExecStop left to run.
    # shellcheck source=/dev/null
    . /usr/lib/os-release
    systemd-tmpfiles --create --inline "L /run/extensions/posix.raw - - - - /var/lib/beamline/extensions/posix_$IMAGE_VERSION.raw" "L /run/confexts/posix.raw - - - - /var/lib/beamline/confexts/posix_$IMAGE_VERSION.raw"
    beamlinectl deactivate posix
    [ ! -e /run/extensions/posix.raw ]
    [ ! -e /run/confexts/posix.raw ]
    state_is posix yes no
    echo BEAMLINE_CTL_UNLINK_RETRY_OK
    # The requeued target also wants this running test; waiting for that target would self-deadlock.
    systemctl start --no-block default.target
    systemctl start beamline-extension@posix.service
    beamlinectl activate posix-devel
    state_is posix yes no
    state_is posix-devel no yes
    state_is desktop-gnome yes yes
    [ -e /run/beamline/inactive/posix ]
    beamlinectl deactivate posix-devel
    echo BEAMLINE_CTL_INACTIVE_REQUEUE_OK
    reboot_to 4
elif [ "$stage" = 4 ]; then
    state_is desktop-gnome yes yes
    state_is posix yes yes
    state_is posix-devel no no
    state_is printing-scanning no no
    [ ! -e /run/beamline/inactive/posix ]
    [ ! -e /run/beamline/active/posix-devel ]
    echo BEAMLINE_CTL_OVERRIDE_REBOOT_OK
else
    echo "unexpected control test stage $stage"; exit 1
fi
trap - EXIT
echo BEAMLINE_CTL_OK
