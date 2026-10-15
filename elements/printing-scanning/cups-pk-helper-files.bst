# SPDX-License-Identifier: MIT

kind: filter
description: cups-pk-helper installed files for the desktop/printing split, without dependencies (D65).

build-depends:
- junctions/gnome-build-meta.bst:core-deps/cups-pk-helper.bst

config:
  exclude:
  - debug
  - devel
  - doc
  include-orphans: true
