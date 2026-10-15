# SPDX-License-Identifier: MIT
#
# The desktop combined with extensions (ci/test-combos; 0.0.4.1, docs/decisions.md D75). Runs as
# root in platform_service_t, the test harness (D90), on a boot where desktop-gnome merged and GDM
# runs. It merges
# the extensions named in the beamline.test.combo credential one at a time, checks each, and
# checks that the desktop survived each /usr and /etc refresh. Never part of an image, so it may
# use dash. The base has no coreutils, so waits use udevadm's timeout instead of sleep(1).

set -u
read -r combo < "$CREDENTIALS_DIRECTORY/beamline.test.combo"
work=/run/beamline-combo
failed=0

result() {
    if [ "$1" = ok ]; then echo "COMBO $2: ok"; else echo "COMBO $2: FAILED"; failed=1; fi
}
check() {  # NAME COMMAND...
    name=$1; shift
    if "$@"; then result ok "$name"; else result failed "$name"; fi
}
# The base has no sleep(1): udevadm waits a second for a device that never appears. A unit
# that fails and restarts would print [FAILED] on the console, which fails the boot.
pause() {
    udevadm wait --timeout=1 /dev/beamline-combo-never 2> /dev/null || :
}
# A confined service's main process runs in its own domain (D95, D96). attr/current ends in a NUL,
# not a newline, so read reports end of file even when it read the context: test the value.
domain() {  # UNIT TYPE
    systemctl start "$1"
    pid=$(systemctl show -P MainPID "$1")
    c=
    { read -r c < "/proc/$pid/attr/current"; } 2> /dev/null
    case "$c" in
        *":$2:"*) result ok "domain-$1" ;;
        *) result failed "domain-$1"; echo "$1: ${c:-no main process}" ;;
    esac
}
# The greeter's session runs in user_t like every session (D96): its session leader,
# gdm-wayland-session, never runs in GDM's own domain.
greeter_session_user() {
    found=0
    for attr in /proc/[0-9]*/attr/current; do
        pid=${attr#/proc/}; pid=${pid%%/*}
        n=
        { read -r n < "/proc/$pid/comm"; } 2> /dev/null
        [ "$n" = gdm-wayland-ses ] || continue
        c=
        { read -r c < "$attr"; } 2> /dev/null
        case "$c" in *:user_t:*) found=1 ;; *) echo "greeter session leader $pid: $c"; return 1 ;; esac
    done
    [ "$found" = 1 ]
}
# Retry a command (evaluated in this shell) about once a second, up to ATTEMPTS times.
retry() {  # ATTEMPTS COMMAND
    attempt=1
    until eval "$2"; do
        [ "$attempt" -lt "$1" ] || return 1
        attempt=$((attempt + 1))
        pause
    done
}
# The PID of the first gnome-shell process. Without a signed-in user, that is GDM's greeter.
shell_pid() {
    for process in /proc/[0-9]*; do
        read -r command < "$process/comm" 2> /dev/null || continue
        if [ "$command" = gnome-shell ]; then
            echo "${process#/proc/}"
            return
        fi
    done
}
# GDM runs a greeter whose GNOME Shell stays up. A greeter session alone is not enough: GDM
# opens a new one for every attempt while a failing Shell is restarted, then gives up.
greeter_stable() {
    systemctl is-active --quiet display-manager.service || return 1
    first=$(shell_pid)
    [ -n "$first" ] || return 1
    pause; pause; pause; pause; pause
    [ "$(shell_pid)" = "$first" ]
}
# The Shell started before a merge keeps the libraries it mapped; restarting GDM checks that a
# Shell started after it still works (D75: the extensions' linker caches shadowed each other).
desktop_alive() {  # STAGE
    check "desktop-$1-shell-present" test -x /usr/bin/gnome-shell
    check "desktop-$1-greeter" retry 30 greeter_stable
    systemctl restart display-manager.service
    check "desktop-$1-greeter-restarted" retry 30 greeter_stable
}

printing() {
    check printing-merge beamlinectl --no-ask-password activate printing-scanning
    check printing-cups systemctl start cups.service
    domain cups.service cupsd_t
    # Debug logging names the filter chain and its errors if the job fails. cupsd restarts for it,
    # so the queue is created once the scheduler answers again.
    check printing-debug-logging cupsctl --debug-logging
    # A virtual IPP Everywhere printer, a CUPS queue for it, and a real job through the filters.
    ippeveprinter -v -p 8631 -r off -k "Beamline Virtual" > "$work/ippeveprinter.log" 2>&1 &
    ipp=$!
    check printing-virtual-printer retry 30 "ipptool -q ipp://localhost:8631/ipp/print get-printer-attributes.test > /dev/null"
    check printing-queue retry 30 "lpadmin -p beamline-virtual -E -v ipp://localhost:8631/ipp/print -m everywhere"
    check printing-submit lp -d beamline-virtual /etc/os-release
    # shellcheck disable=SC2016 # evaluated by retry
    if retry 60 'case "$(lpstat -W completed -o beamline-virtual)" in *beamline-virtual-*) true ;; *) false ;; esac'; then
        result ok printing-completed
    else
        result failed printing-completed
        lpstat -l -p beamline-virtual
        lpstat -W all -o beamline-virtual
        while IFS= read -r line; do
            case "$line" in *"[Job "*) echo "cups: $line" ;; esac
        done < /var/log/cups/error_log
        while IFS= read -r line; do echo "ippeveprinter: $line"; done < "$work/ippeveprinter.log"
    fi
    kill "$ipp" 2> /dev/null
    # SANE's test backend through a scratch configuration: /etc/sane.d/dll.conf leaves it disabled.
    printf 'test\n' > "$work/dll.conf"
    if SANE_CONFIG_DIR="$work:" scanimage -d test --format=pnm -o "$work/scan.pnm" && [ -s "$work/scan.pnm" ]; then
        result ok printing-scan-test-backend
    else
        result failed printing-scan-test-backend
    fi
}

echo "COMBO desktop + $combo"
# GDM gets its job only after the boot's extension merge queues default.target again
# (beamline-extensions-start.service), so ordering after it cannot be expressed in the unit.
check desktop-started retry 120 greeter_stable
domain display-manager.service xdm_t
domain accounts-daemon.service accountsd_t
domain flatpak-system-helper.service flatpak_helper_t
check greeter-session-user-t greeter_session_user
desktop_alive before
for extension in $combo; do
    case "$extension" in
        posix) check posix systemctl start beamline-posix-check.service ;;
        devel) check devel systemctl start beamline-devel-check.service ;;
        printing) printing ;;
        *) result failed "unknown-extension-$extension" ;;
    esac
    desktop_alive "after-$extension"
done

# This check is still a boot job, so the system reports `starting`; no unit may have failed.
units=$(systemctl list-units --state=failed --no-legend --plain --no-pager)
if [ -z "$units" ]; then
    result ok no-failed-units
else
    result failed failed-units
    echo "$units"
fi
[ "$failed" = 0 ] && echo BEAMLINE_COMBO_OK || echo BEAMLINE_COMBO_FAILED
