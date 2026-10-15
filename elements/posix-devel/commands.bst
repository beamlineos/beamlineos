# SPDX-License-Identifier: MIT
kind: manual
description: C17 language selector and lex invocation for the independent development extension
build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
runtime-depends:
- junctions/freedesktop-sdk.bst:components/gcc.bst
- posix-devel/flex-files.bst
variables:
  strip-binaries: ''
config:
  install-commands:
  - install -Dm755 c17 "%{install-root}/usr/bin/c17"
  - ln -s flex "%{install-root}/usr/bin/lex"
sources:
- kind: local
  path: files/posix-devel/c17
