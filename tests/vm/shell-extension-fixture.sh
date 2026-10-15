#!/usr/bin/sh
# SPDX-License-Identifier: MIT
# Make fixture setup failures visible before systemd reports the failed test unit.
set -eu
PASSWORD=dev homectl activate dev
fixture=/home/dev/.local/share/gnome-shell/extensions/beamline-test@example.test
systemd-tmpfiles --create --inline \
    "z /home/dev - - - -" \
    "d /home/dev/.local 0700 dev dev -" \
    "d /home/dev/.local/share 0700 dev dev -" \
    "d /home/dev/.local/share/gnome-shell 0700 dev dev -" \
    "d /home/dev/.local/share/gnome-shell/extensions 0700 dev dev -" \
    "d $fixture 0700 dev dev -"
# Write credential contents into new files with the requested mode and ownership.
# C copies preserve credential-file permissions instead.
SYSTEMD_LOG_TARGET=console systemd-tmpfiles --create --inline \
    "f+^ $fixture/metadata.json 0600 dev dev - beamline.test.shell-extension.metadata" \
    "f+^ $fixture/extension.js 0600 dev dev - beamline.test.shell-extension.code"
homectl deactivate dev
echo BEAMLINE_SHELL_EXTENSION_FIXTURE_READY
