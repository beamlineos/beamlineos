# SPDX-License-Identifier: MIT

kind: compose
description: |
  The Virt base and the installer's content, composed and integrated together.
  extensions/installer.bst subtracts the base.

build-depends:
- profiles/virt.bst
- image/integration-tools.bst
- installer/installer.bst

config:
  exclude:
  - debug
  - devel
  - doc
  - tests
  include-orphans: true
