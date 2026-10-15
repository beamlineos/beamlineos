# SPDX-License-Identifier: MIT

kind: stack
description: |
  Virt profile (docs/spec.md §3.2): base + virtio-focused kernel + networkd.
  The deterministic CI and integration-test target.

depends:
- base/base.bst
- kernel/linux-virt.bst
- profiles/virt-config.bst
