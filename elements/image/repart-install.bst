# SPDX-License-Identifier: MIT

kind: import
description: systemd-repart definitions for the installer medium (docs/decisions.md D106).

config:
  target: '%{datadir}/%{os-id}/repart/install'

sources:
- kind: local
  path: files/repart/install
