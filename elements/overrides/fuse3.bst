# SPDX-FileCopyrightText: Freedesktop-SDK Developers
# SPDX-License-Identifier: MIT
# Copied from Freedesktop SDK 809013202493a2676672959850587e5013ae59e4,
# elements/components/fuse3.bst. Changes: junction prefixes; disable mtab helpers
# for immutable /etc and the single-program fusermount_t domain; wire the option
# into its existing compile guard, which upstream 3.18.3 omits (D68).

kind: meson

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/buildsystem-meson.bst

depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-minimal.bst

runtime-depends:
- junctions/freedesktop-sdk.bst:components/util-linux-full.bst

variables:
  meson-local: >-
    -Duseroot=false
    -Dexamples=false
    -Dtests=false
    -Ddisable-mtab=true

config:
  configure-commands:
    (>):
    # Gate the generated macro before building downstream users of this library.
    - python3 -c 'from pathlib import Path; assert "#define IGNORE_MTAB 1" in Path("%{build-dir}/fuse_config.h").read_text()'
  install-commands:
    (>):
    - rm -r "%{install-root}/etc/init.d"

public:
  bst:
    integration-commands:
    - |
      [ -f "%{bindir}/fusermount" ] || ln -s fusermount3 "%{bindir}/fusermount"
  initial-script:
    script: |
      #!/bin/bash
      sysroot="${1}"
      chmod 4755 "${sysroot}%{bindir}/fusermount3"
  cpe:
    vendor: fuse_project
    name: fuse

sources:
- kind: git_repo
  url: github:libfuse/libfuse.git
  track: fuse-*
  exclude:
  - "*rc*"
- kind: patch
  path: files/patches/fuse-disable-mtab.patch
