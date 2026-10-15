# SPDX-FileCopyrightText: Freedesktop-SDK Developers
# SPDX-License-Identifier: MIT
#
# Override of FDSDK components/erofs-utils.bst: mkfs.erofs with --file-contexts, so
# filesystem images are labelled when they are created (docs/security.md §19.1).
#
# Copied from: freedesktop-sdk c67967f99ce9aafd75bf5b3091f5d2da094bdd61
#   elements/components/erofs-utils.bst
# Changes from the original: source refs live in project.refs (ref-storage), dependencies
# carry the junction prefix, libselinux is a dependency, --with-selinux, and
# project_licensedir keeps FDSDK's path.

kind: autotools

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/buildsystem-autotools.bst

depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-minimal.bst
- junctions/freedesktop-sdk.bst:bootstrap/xxhash.bst
- junctions/freedesktop-sdk.bst:bootstrap/xz.bst
- junctions/freedesktop-sdk.bst:components/fuse3.bst
- junctions/freedesktop-sdk.bst:components/lz4.bst
# Uses libuuid only
- junctions/freedesktop-sdk.bst:components/util-linux-libs.bst
- junctions/freedesktop-sdk.bst:bootstrap/libselinux.bst

variables:
  # Keep FDSDK's license directory, as in overrides/systemd-base.bst.
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
