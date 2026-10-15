# SPDX-License-Identifier: MIT

kind: import
description: |
  Human-maintained kernel configuration fragments (docs/spec.md §11.3). A separate
  element so that editing a fragment rebuilds every kernel that uses it.

config:
  target: '%{datadir}/%{os-id}/kernel-config'

sources:
- kind: local
  path: files/kernel/config
