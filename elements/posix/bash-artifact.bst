# SPDX-License-Identifier: MIT

kind: filter
description: |
  FDSDK's bash, its own runtime files only: no dependencies, no debug, devel or doc
  domains. posix/bash.bst takes /usr/bin/sh out of it (docs/decisions.md D37).

build-depends:
- junctions/freedesktop-sdk.bst:bootstrap/bash.bst

config:
  exclude:
  - debug
  - devel
  - doc
  include-orphans: true
