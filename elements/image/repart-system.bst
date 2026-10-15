# SPDX-License-Identifier: MIT

kind: import
description: |
  systemd-repart definitions for the SYSTEM image and its dm-verity hash tree (docs/spec.md
  §13, §14), used by image/system-virt.bst.

config:
  target: '%{datadir}/%{os-id}/repart/system'

sources:
- kind: local
  path: files/repart/system
