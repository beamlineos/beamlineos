# SPDX-License-Identifier: MIT

kind: import
description: |
  The development verity signing key and certificate (files/keys/dev/verity; DEVELOPMENT
  ONLY, docs/security.md §5.4, §19.4). Build-only: extension images are signed with it.
  Never part of an image; base/verity-trust.bst ships the certificate alone.

config:
  target: '%{datadir}/%{os-id}/keys/verity'

sources:
- kind: local
  path: files/keys/dev/verity
