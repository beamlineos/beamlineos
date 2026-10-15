# SPDX-License-Identifier: MIT

kind: import
description: |
  The development Secure Boot db key and certificate (files/keys/dev/uki; DEVELOPMENT ONLY,
  docs/security.md §5.4, §19.4). Build-only: image/uki-virt.bst stages it to sign UKIs and
  systemd-boot. Never part of an image.

config:
  target: '%{datadir}/%{os-id}/keys/uki'

sources:
- kind: local
  path: files/keys/dev/uki
