# SPDX-License-Identifier: MIT

kind: meson
description: |
  The default human login shell: a C stub that prints how to enable the POSIX
  environment, and refuses to interpret input (docs/spec.md §6, §18.3, D62).

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/buildsystem-meson.bst

depends:
- base/runtime.bst

sources:
- kind: local
  path: files/beamline-shell
