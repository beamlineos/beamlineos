#!/usr/bin/sh
# SPDX-License-Identifier: MIT
# Runs only in user_t as UID 0. Exercise the D-Bus equivalent of ExecStart=+.
set -eu
unit=beamline-transient-privileged.service
busctl -- call org.freedesktop.systemd1 /org/freedesktop/systemd1 \
    org.freedesktop.systemd1.Manager StartTransientUnit 'ssa(sv)a(sa(sv))' \
    "$unit" replace 3 Type s oneshot RemainAfterExit b true \
    ExecStartEx 'a(sasas)' 1 /usr/bin/sh 3 sh -c \
    'read -r c < /proc/self/attr/current; printf "%s\n" "$c" > /var/tmp/beamline-transient-context' \
    1 privileged 0
for attempt in 1 2 3 4 5 6 7 8 9 10; do
    if [ -s /var/tmp/beamline-transient-context ]; then
        read -r context < /var/tmp/beamline-transient-context
        [ "$context" = user_u:user_r:user_t:s0:c0 ]
        echo TRANSIENT_PRIVILEGED_P0
        exit 0
    fi
    sleep 1
done
exit 1
