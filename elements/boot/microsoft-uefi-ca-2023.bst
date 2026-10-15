# SPDX-License-Identifier: MIT

kind: import
description: |
  Microsoft UEFI CA 2023, the successor of the 2011 CA (docs/decisions.md D113): the file as published, pinned by its SHA-256
  ([archive.microsoft-uefi-ca-2023] in policy/tracking.toml).

config:
  target: '%{datadir}/%{os-id}/secure-boot/upstream'

sources:
- kind: remote
  url: microsoft_pki:microsoft%20uefi%20ca%202023.crt
  filename: microsoft-uefi-ca-2023.crt
