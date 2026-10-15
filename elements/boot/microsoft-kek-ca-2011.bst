# SPDX-License-Identifier: MIT

kind: import
description: |
  Microsoft Corporation KEK CA 2011 (docs/decisions.md D113): the file as published, pinned by its SHA-256
  ([archive.microsoft-kek-ca-2011] in policy/tracking.toml).

config:
  target: '%{datadir}/%{os-id}/secure-boot/upstream'

sources:
- kind: remote
  url: microsoft_pki:MicCorKEKCA2011_2011-06-24.crt
  filename: microsoft-kek-ca-2011.crt
