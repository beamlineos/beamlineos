# SPDX-License-Identifier: MIT
# AutoGen 5.18.16 uses the Guile 2.2 API. Build-only, never in an image (D63).
kind: autotools
build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/buildsystem-autotools.bst
- junctions/freedesktop-sdk.bst:components/flex.bst
- junctions/freedesktop-sdk.bst:components/bison.bst
- junctions/freedesktop-sdk.bst:components/texinfo.bst
depends:
- build-tools/gc.bst
- junctions/freedesktop-sdk.bst:components/libffi.bst
- junctions/freedesktop-sdk.bst:components/gmp.bst
- junctions/freedesktop-sdk.bst:components/libunistring.bst
variables:
  conf-local: --prefix=%{prefix} --libdir=%{libdir} --disable-static --without-libreadline-prefix
sources:
- kind: tar
  url: gnu:guile/guile-2.2.7.tar.xz
