# SPDX-License-Identifier: MIT
kind: filter
description: bison's own SDK files without its GNU coreutils runtime closure (D69)
build-depends:
- junctions/freedesktop-sdk.bst:components/bison.bst
config:
  include-orphans: true
