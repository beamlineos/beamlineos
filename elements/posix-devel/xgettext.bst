# SPDX-License-Identifier: MIT
kind: script
description: Development xgettext; its support libraries are supplied by the POSIX content
build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
- filename: posix/gettext-artifact.bst
  config:
    location: /gettext
variables:
  strip-binaries: ''
config:
  commands:
  - install -Dm755 /gettext/usr/bin/xgettext "%{install-root}/usr/bin/xgettext"
