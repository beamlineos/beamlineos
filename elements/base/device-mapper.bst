# SPDX-License-Identifier: MIT

kind: stack
description: |
  Device-mapper support for dm-verity (docs/spec.md §13, §14): libdevmapper, dmsetup and
  device-mapper's udev rules (docs/decisions.md D47).

depends:
- base/device-mapper-files.bst
- junctions/freedesktop-sdk.bst:components/libdevmapper.bst
- junctions/freedesktop-sdk.bst:components/systemd-libs.bst
