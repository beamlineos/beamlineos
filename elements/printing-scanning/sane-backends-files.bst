# SPDX-License-Identifier: MIT

kind: filter
description: sane-backends installed files for the desktop/printing split, without dependencies (D65).

build-depends:
- junctions/gnome-build-meta.bst:freedesktop-sdk-extra.bst:components/sane-backends.bst

config:
  exclude:
  - debug
  - devel
  - doc
  include-orphans: true
