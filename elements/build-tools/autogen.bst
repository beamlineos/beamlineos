# SPDX-License-Identifier: MIT

kind: autotools
build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/buildsystem-autotools.bst
- junctions/freedesktop-sdk.bst:components/texinfo.bst
depends:
- build-tools/guile.bst
variables:
  
  
  
  conf-local: >-
    --prefix=%{prefix} --libdir=%{libdir} --without-libxml2
    --disable-dependency-tracking
    ag_cv_with_libxml2=no
    CFLAGS="$CFLAGS -std=gnu17 -Wno-error=discarded-qualifiers"
sources:
- kind: tar
  url: gnu:autogen/rel5.18.16/autogen-5.18.16.tar.xz
- kind: patch
  path: files/posix/autogen-compat.patch
