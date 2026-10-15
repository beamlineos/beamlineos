# SPDX-License-Identifier: MIT

kind: import
description: |
  Microsoft Corporation KEK 2K CA 2023 (docs/decisions.md D113): the file as published, pinned by its SHA-256
  ([archive.microsoft-kek-ca-2023] in policy/tracking.toml).

config:
  target: '%{datadir}/%{os-id}/secure-boot/upstream'

sources:
- kind: remote
  url: microsoft_pki:microsoft%20corporation%20kek%202k%20ca%202023.crt
  filename: microsoft-kek-ca-2023.crt
