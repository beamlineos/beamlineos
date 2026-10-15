# SPDX-License-Identifier: MIT

kind: filter
description: system-config-printer installed files for the desktop/printing split, without dependencies (D65).

build-depends:
- junctions/gnome-build-meta.bst:core-deps/system-config-printer.bst

config:
  exclude:
  - debug
  - devel
  - doc
  include-orphans: true
