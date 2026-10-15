# SPDX-License-Identifier: MIT

kind: filter
description: foomatic-db installed files for the desktop/printing split, without dependencies (D65).

build-depends:
- junctions/freedesktop-sdk.bst:components/foomatic-db.bst

config:
  exclude:
  - debug
  - devel
  - doc
  include-orphans: true
