# SPDX-License-Identifier: MIT
kind: compose
description: Base plus complete independent development content, including headers and debug symbols
build-depends:
- profiles/virt.bst
- junctions/freedesktop-sdk.bst:bootstrap/gzip.bst
- posix-devel/posix-devel.bst
config:
  exclude:
  - tests
  include-orphans: true
