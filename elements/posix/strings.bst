# SPDX-License-Identifier: MIT
kind: script
description: POSIX strings from the SDK's binutils, without development commands
build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
- filename: junctions/freedesktop-sdk.bst:components/binutils.bst
  config:
    location: /binutils
variables:
  strip-binaries: ''
config:
  commands:
  - install -Dm755 /binutils/usr/bin/strings "%{install-root}/usr/bin/strings"
  - |
    # The native strings needs BFD and sframe, without development commands.
    # runtime-gnu has no find; use explicit SDK library globs instead.
    for file in /binutils%{libdir}/libbfd*.so* /binutils%{libdir}/libsframe*.so*; do
      [ -e "$file" ] || [ -L "$file" ] || continue
      path="${file#/binutils}"
      mkdir -p "%{install-root}$(dirname "$path")"
      cp -a "$file" "%{install-root}${path}"
    done
    test -f "%{install-root}%{libdir}"/libbfd-*.so
    test -f "%{install-root}%{libdir}"/libsframe.so.*.*.*
