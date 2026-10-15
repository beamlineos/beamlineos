# SPDX-License-Identifier: MIT

kind: import
description: |
  Virt profile configuration: systemd-networkd (docs/spec.md §10.2) and the boot-time
  repart definitions that grow DATA to the end of the disk (§15).

sources:
- kind: local
  path: files/network/networkd
  directory: usr/lib/systemd/network
- kind: local
  path: files/repart/virt-runtime
  directory: usr/lib/repart.d
