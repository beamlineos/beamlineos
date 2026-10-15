# SPDX-License-Identifier: MIT

kind: compose
description: |
  The Virt base and the desktop-gnome content, composed and integrated together (schemas,
  loaders, linker cache over the merged tree). extensions/desktop-gnome.bst subtracts the
  base.

build-depends:
- profiles/virt.bst
- image/integration-tools.bst
- desktop/gnome.bst

config:
  exclude:
  - debug
  - devel
  - doc
  - tests
  include-orphans: true
