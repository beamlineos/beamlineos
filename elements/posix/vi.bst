# SPDX-License-Identifier: MIT
kind: manual
description: The POSIX vi invocation of SDK Vim, which installs vim and ex (§7.2, D63)
build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
runtime-depends:
- junctions/freedesktop-sdk.bst:components/vim.bst
variables:
  strip-binaries: ''
config:
  install-commands:
  - mkdir -p "%{install-root}%{bindir}"
  - ln -s vim "%{install-root}%{bindir}/vi"
