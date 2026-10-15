# SPDX-License-Identifier: MIT

kind: import
description: Policy checker and its allowlist, staged into test sandboxes.

config:
  target: '%{libexecdir}/%{os-id}-tests'

sources:
- kind: local
  path: policy/base-user-tools.txt
- kind: local
  path: policy/base-virtualization.txt
- kind: local
  path: tools/check-policy.py
- kind: local
  path: tools/check-libraries.py
- kind: local
  path: policy/prune/libraries-allowed.txt
- kind: local
  path: policy/unit-shell-allowlist.txt
