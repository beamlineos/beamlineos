# SPDX-License-Identifier: MIT

kind: compose
description: |
  The Virt base and the posix extension content, composed and integrated together, as
  image/root-virt-tree.bst does for the root. extensions/posix.bst subtracts the base.
  FDSDK's integration commands run on uutils here, so of the integration toolbox only
  gzip is needed; GNU coreutils would collide with uutils.

build-depends:
- profiles/virt.bst
- junctions/freedesktop-sdk.bst:bootstrap/gzip.bst
- posix/posix.bst

config:
  exclude:
  - debug
  - devel
  - tests
  include-orphans: true
