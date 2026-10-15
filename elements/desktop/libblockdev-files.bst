# SPDX-License-Identifier: MIT

kind: filter
description: Own libblockdev runtime files for identifying its optional LVM plugins (D67).
build-depends:
- junctions/freedesktop-sdk.bst:components/libblockdev.bst
config:
  exclude:
  - debug
  - devel
  - doc
  include-orphans: true
