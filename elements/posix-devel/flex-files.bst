# SPDX-License-Identifier: MIT
kind: filter
description: flex's own SDK files without its GNU coreutils runtime closure (D69)
build-depends:
- junctions/freedesktop-sdk.bst:components/flex.bst
config:
  include-orphans: true
