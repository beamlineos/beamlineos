# SPDX-License-Identifier: MIT
kind: filter
description: SDK procps runtime files, after its uutils candidate failed its own suite (D63)
build-depends:
- junctions/freedesktop-sdk.bst:components/procps.bst
config:
  exclude:
  - debug
  - devel
  include-orphans: true
