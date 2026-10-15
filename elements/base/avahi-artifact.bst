# SPDX-License-Identifier: MIT

kind: filter
description: Avahi's own runtime files, without the upstream GLib/Python closure (D65).

build-depends:
- junctions/freedesktop-sdk.bst:components/avahi.bst

config:
  exclude:
  - debug
  - devel
  - doc
  include-orphans: true
