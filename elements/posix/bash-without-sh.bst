# SPDX-License-Identifier: MIT

kind: script
description: |
  FDSDK's bash files without its /usr/bin/sh link (docs/decisions.md D37). BuildStream
  filters select split domains, and FDSDK defines none that isolates /usr/bin/sh, so the
  filtered artifact is copied without it. posix/bash.bst adds bash's runtime dependency.

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
- filename: posix/bash-artifact.bst
  config:
    location: /input

config:
  commands:
  - cp -a /input/. "%{install-root}/"
  - rm "%{install-root}%{bindir}/sh"
  - test -x "%{install-root}%{bindir}/bash"
