# SPDX-License-Identifier: MIT
# Deliberately pinned build-only bootstrap for AutoGen (D63), never in an image.
kind: autotools
build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/buildsystem-autotools.bst
variables:
  conf-local: --prefix=%{prefix} --libdir=%{libdir} --disable-static
sources:
- kind: tar
  url: github:bdwgc/bdwgc/releases/download/v8.2.10/gc-8.2.10.tar.gz
