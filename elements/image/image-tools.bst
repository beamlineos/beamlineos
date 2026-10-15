# SPDX-License-Identifier: MIT

kind: import
description: |
  Image-building helpers staged into image elements: the extension composer, the artifact
  policy checker (docs/decisions.md D36), the pruning tool, its lists and the library
  check (D88), the pinned system IDs with their tool (D106), the Secure Boot enrollment
  file generator (D111) and the installation components' list (D113).

config:
  target: '%{libexecdir}/%{os-id}-image-tools'

sources:
- kind: local
  path: tools/build-extension.py
- kind: local
  path: tools/check-policy.py
- kind: local
  path: tools/prune-tree.py
- kind: local
  path: tools/check-libraries.py
- kind: local
  path: tools/extension-paths.py
- kind: local
  path: tools/pin-sysusers.py
- kind: local
  path: tools/make-enrollment.py
- kind: local
  path: policy/system-ids.txt
- kind: local
  path: policy/prune
  directory: prune
- kind: local
  path: policy/posix-utilities.txt
- kind: local
  path: policy/base-user-tools.txt
- kind: local
  path: policy/base-virtualization.txt
- kind: local
  path: policy/base-installer.txt
