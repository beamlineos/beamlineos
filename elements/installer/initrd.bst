# SPDX-License-Identifier: MIT

kind: import
description: |
  The installer UKI's extra initrd content (docs/decisions.md D113): the unit that hands the
  installer extension from /.extra/sysext to the root's /run/extensions, where the root's
  systemd-sysext merges it. image/uki-virt.bst packs it as a second cpio into the installer UKI only.

config:
  target: '%{datadir}/%{os-id}/installer-initrd/usr/lib/systemd/system'

sources:
- kind: local
  path: files/installer/initrd
