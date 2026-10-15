# SPDX-License-Identifier: MIT

kind: compose
description: |
  The Virt root filesystem tree: the profile's runtime closure with integration commands
  applied and build-only domains removed. Still contains the integration toolbox;
  image/root-virt.bst strips it.

build-depends:
- profiles/virt.bst
- image/integration-tools.bst

config:
  exclude:
  - debug
  - devel
  - doc
  - tests
  include-orphans: true
