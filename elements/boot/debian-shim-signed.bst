# SPDX-License-Identifier: MIT

kind: import
description: |
  Debian's shim for arm64 (trixie), signed by Microsoft's UEFI CA (docs/decisions.md D113): the file as published, pinned by its SHA-256
  ([archive.debian-shim-signed] in policy/tracking.toml).

config:
  target: '%{datadir}/%{os-id}/secure-boot/upstream'

sources:
- kind: remote
  url: debian:pool/main/s/shim-signed/shim-signed_1.51~1+deb13u1+16.1-2~deb13u1_arm64.deb
  filename: shim-signed.deb
