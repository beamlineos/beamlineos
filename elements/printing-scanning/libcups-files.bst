# SPDX-License-Identifier: MIT

kind: filter
description: libcups installed files for the desktop/printing split, without dependencies (D65).

build-depends:
- junctions/freedesktop-sdk.bst:components/cups.bst

config:
  exclude:
  - debug
  - devel
  - doc
  include-orphans: true
