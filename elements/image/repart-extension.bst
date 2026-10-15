# SPDX-License-Identifier: MIT

kind: import
description: |
  systemd-repart definitions for extension images (docs/spec.md §8, docs/decisions.md D50):
  EROFS, a dm-verity hash tree, and a signature over its root hash.

config:
  target: '%{datadir}/%{os-id}/repart/extension'

sources:
- kind: local
  path: files/repart/extension
