# SPDX-License-Identifier: MIT
kind: script
description: POSIX gettext, ngettext and msgfmt; xgettext belongs in posix-devel
build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
- filename: posix/gettext-artifact.bst
  config:
    location: /gettext
variables:
  strip-binaries: ''
config:
  commands:
  - cp -a /gettext/. "%{install-root}/"
  - rm -f "%{install-root}/usr/bin/xgettext"
