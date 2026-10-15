# SPDX-License-Identifier: MIT

kind: stack
description: |
  The smallest bootable Beamline userspace (docs/spec.md §5), shared by every profile.
  Additions need a demonstrated runtime requirement.

depends:
- base/runtime.bst
- base/systemd.bst
- base/ipc.bst
- base/avahi.bst
- base/security.bst
- base/shell-compat.bst
- base/beamline-shell.bst
- base/beamlinectl.bst
- base/os-release.bst
- base/config.bst
