# SPDX-License-Identifier: MIT

kind: filter
description: Own package files removed from desktop-gnome (0.0.4 step 6, D67).
build-depends:
- junctions/freedesktop-sdk.bst:components/iptables.bst
config:
  exclude:
  - debug
  - devel
  - doc
  include-orphans: true
