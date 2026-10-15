# SPDX-License-Identifier: MIT

kind: import
description: |
  Microsoft Corporation UEFI CA 2011, which signs third-party boot loaders such as shim (docs/decisions.md D113): the file as published, pinned by its SHA-256
  ([archive.microsoft-uefi-ca-2011] in policy/tracking.toml).

config:
  target: '%{datadir}/%{os-id}/secure-boot/upstream'

sources:
- kind: remote
  url: microsoft_pki:MicCorUEFCA2011_2011-06-27.crt
  filename: microsoft-uefi-ca-2011.crt
