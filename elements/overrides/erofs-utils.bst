# SPDX-FileCopyrightText: Freedesktop-SDK Developers
# SPDX-License-Identifier: MIT










kind: autotools

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/buildsystem-autotools.bst

depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-minimal.bst
- junctions/freedesktop-sdk.bst:bootstrap/xxhash.bst
- junctions/freedesktop-sdk.bst:bootstrap/xz.bst
- junctions/freedesktop-sdk.bst:components/fuse3.bst
- junctions/freedesktop-sdk.bst:components/lz4.bst

- junctions/freedesktop-sdk.bst:components/util-linux-libs.bst
- junctions/freedesktop-sdk.bst:bootstrap/libselinux.bst

variables:
  
  project_licensedir: '%{licensedir}/freedesktop-sdk'
  conf-local: >-
    --enable-lzma
    --enable-lz4
    --enable-fuse
    --enable-multithreading
    --with-selinux

sources:
- kind: git_repo
  url: kernel:linux/kernel/git/xiang/erofs-utils.git
  track: v*.*
