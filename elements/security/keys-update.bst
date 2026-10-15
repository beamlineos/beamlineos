# SPDX-License-Identifier: MIT

kind: import
description: |
  The development update signing key (files/keys/dev/update; DEVELOPMENT ONLY,
  docs/security.md §5.4, §19.4): the OpenPGP secret key that signs a snapshot's SHA256SUMS
  (image/update-virt.bst), and the public keyring systemd-pull verifies against, which
  image/root-virt.bst installs. Build-only; the secret key is never part of an image.

config:
  target: '%{datadir}/%{os-id}/keys/update'

sources:
- kind: local
  path: files/keys/dev/update
