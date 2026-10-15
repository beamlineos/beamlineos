# SPDX-License-Identifier: MIT
kind: import
description: |
  Lists of paths the base leaves out, shared by assembly and policy checks: the base/POSIX
  command split (D63) and the virtualization services (D87).
config:
  target: /usr/share/beamline/policy
sources:
- kind: local
  path: policy/base-user-tools.txt
- kind: local
  path: policy/base-virtualization.txt
