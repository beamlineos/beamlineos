# SPDX-License-Identifier: MIT

kind: import
description: |
  The file-mode list applied when filesystems are created (files/image/permissions,
  docs/decisions.md D31).

config:
  target: '%{datadir}/%{os-id}/image'

sources:
- kind: local
  path: files/image
