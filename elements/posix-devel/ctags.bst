# SPDX-License-Identifier: MIT
kind: autotools
description: GNU ctags from Emacs etags; only the native tags program is installed (D69)
(@):
- include/posix-devel/emacs-commit.yml
build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/buildsystem-autotools.bst
- junctions/freedesktop-sdk.bst:components/gmp.bst
- junctions/freedesktop-sdk.bst:components/texinfo.bst
- junctions/freedesktop-sdk.bst:bootstrap/ncurses.bst
- junctions/freedesktop-sdk.bst:components/gzip.bst
depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-minimal.bst
variables:
  autogen: ./autogen.sh autoconf
  conf-local: >-
    --without-all --without-x --without-native-compilation --with-dumping=none
config:
  build-commands:
  - make -C lib-src -j%{max-jobs} etags
  - |
    make -C test/manual/etags check \
      ETAGS_PROG="%{build-root}/lib-src/etags" \
      CTAGS_PROG="%{build-root}/lib-src/etags --ctags"
  install-commands:
  - install -Dm755 lib-src/etags "%{install-root}/usr/bin/etags"
  - install -Dm755 ctags "%{install-root}/usr/bin/ctags"
  - install -Dm644 COPYING "%{install-root}/usr/share/licenses/gnu-ctags/COPYING"
sources:
- kind: tar
  url: github:emacs-mirror/emacs/archive/%{emacs-commit}.tar.gz
- kind: local
  path: files/posix-devel/ctags
