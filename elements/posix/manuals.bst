# SPDX-License-Identifier: MIT

kind: manual
description: Published POSIX manual pages, with their required license notices
build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
runtime-depends:
- junctions/freedesktop-sdk.bst:components/mandoc.bst
variables:
  strip-binaries: ''
config:
  install-commands:
  - |
    mkdir -p "%{install-root}%{datadir}/man"
    cp -a man0p man1p man3p "%{install-root}%{datadir}/man/"
    install -Dm644 POSIX-COPYRIGHT "%{install-root}%{datadir}/licenses/man-pages-posix/POSIX-COPYRIGHT"
sources:
- kind: tar
  url: kernel_files:linux/docs/man-pages/man-pages-posix/man-pages-posix-2017-a.tar.xz

public:
  bst:
    
    
    integration-commands:
    - makewhatis %{datadir}/man
