# SPDX-License-Identifier: MIT

kind: manual
description: |
  Build-time SELinux policy tools (docs/security.md §19.2, docs/decisions.md D35): secilc
  compiles the CIL policy and setfiles validates its file contexts. Built from SELinux
  userspace `main`, with libsepol and libselinux linked statically, under a private
  prefix. Never part of an image: the runtime libselinux is FDSDK's.

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/buildsystem-autotools.bst
- junctions/freedesktop-sdk.bst:components/flex.bst
- junctions/freedesktop-sdk.bst:bootstrap/pcre2.bst

variables:
  selinux-tools-dir: '%{libexecdir}/%{os-id}/selinux-tools'


config:
  build-commands:
  - make -C libsepol/src libsepol.a
  # libselinux/Makefile normally exports the PCRE2 flags to src/.
  - |
    make -C libselinux/src libselinux.a CPPFLAGS="-I$(pwd)/libsepol/include" \
      PCRE_CFLAGS="-DUSE_PCRE2 -DPCRE2_CODE_UNIT_WIDTH=8"
  - |
    make -C secilc secilc \
      CPPFLAGS="-I$(pwd)/libsepol/include" LDFLAGS="-L$(pwd)/libsepol/src"
  - |
    make -C policycoreutils/setfiles setfiles AUDITH=n \
      CPPFLAGS="-I$(pwd)/libsepol/include" LDFLAGS="-L$(pwd)/libsepol/src" \
      LIBSELINUX_LDLIBS="-lselinux -lpcre2-8"

  install-commands:
  - |
    install -Dm755 -t "%{install-root}%{selinux-tools-dir}" \
      secilc/secilc policycoreutils/setfiles/setfiles

sources:
- kind: git
  url: github:SELinuxProject/selinux.git
  track: main
  ref-format: git-describe
