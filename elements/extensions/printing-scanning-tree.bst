# SPDX-License-Identifier: MIT

kind: compose
description: Base and printing-scanning content, composed and integrated together (D65).

build-depends:
- profiles/virt.bst
- image/integration-tools.bst
- printing-scanning/printing-scanning.bst

config:
  exclude:
  - debug
  - devel
  - doc
  - tests
  include-orphans: true
