# SPDX-License-Identifier: MIT
kind: filter
description: Gettext's own runtime files, without its GNU findutils/diffutils closure (D63)
build-depends:
- junctions/freedesktop-sdk.bst:components/gettext.bst
config:
  exclude:
  - debug
  - devel
  include-orphans: true
