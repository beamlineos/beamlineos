# SPDX-License-Identifier: MIT
kind: manual
description: GNU procps, with kill and uptime supplied by uutils coreutils (§7.2, D63)
build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
- filename: posix/procps-artifact.bst
  config:
    location: /procps
runtime-depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-minimal.bst
- junctions/freedesktop-sdk.bst:components/systemd-libs.bst
variables:
  strip-binaries: ''
config:
  install-commands:
  - cp -a /procps/. "%{install-root}/"
  - rm -f "%{install-root}/usr/bin/kill" "%{install-root}/usr/bin/uptime"
