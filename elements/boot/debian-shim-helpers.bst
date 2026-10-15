# SPDX-License-Identifier: MIT

kind: import
description: |
  Debian's MokManager and fallback for arm64 (trixie), signed by Debian's Secure Boot CA (docs/decisions.md D113): the file as published, pinned by its SHA-256
  ([archive.debian-shim-helpers] in policy/tracking.toml).

config:
  target: '%{datadir}/%{os-id}/secure-boot/upstream'

sources:
- kind: remote
  url: debian:pool/main/s/shim-helpers-arm64-signed/shim-helpers-arm64-signed_1+16.1+2~deb13u1_arm64.deb
  filename: shim-helpers.deb
