# SPDX-FileCopyrightText: Freedesktop-SDK Developers
# SPDX-License-Identifier: MIT
# Copied from Freedesktop SDK 809013202493a2676672959850587e5013ae59e4,
# elements/components/libcupsfilters.bst. Changes: junction prefixes; upstream's unreleased fix
# e14bad4061 as a patch, without which every raster job fails (0.0.4.1 K2, D84); built in the
# source tree with the plugin's defaults, as erofs-utils is, so FDSDK's config.h link for its
# out-of-tree build is dropped; project_licensedir keeps FDSDK's path. The source stays
# FDSDK's selection (policy/tracking.toml [recipe.libcupsfilters]). Drop this override once FDSDK
# selects a libcupsfilters release that contains the fix.

kind: autotools

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/buildsystem-autotools.bst
- junctions/freedesktop-sdk.bst:components/mutool.bst

depends:
- junctions/freedesktop-sdk.bst:components/cups.bst
- junctions/freedesktop-sdk.bst:components/dbus.bst
- junctions/freedesktop-sdk.bst:components/fontconfig.bst
- junctions/freedesktop-sdk.bst:components/ghostscript.bst
- junctions/freedesktop-sdk.bst:components/jpeg.bst
- junctions/freedesktop-sdk.bst:components/lcms.bst
- junctions/freedesktop-sdk.bst:components/libexif.bst
- junctions/freedesktop-sdk.bst:components/libjxl.bst
- junctions/freedesktop-sdk.bst:components/libpng.bst
- junctions/freedesktop-sdk.bst:components/libtiff.bst
- junctions/freedesktop-sdk.bst:components/pdfio.bst
- junctions/freedesktop-sdk.bst:components/poppler.bst

variables:
  project_licensedir: '%{licensedir}/freedesktop-sdk'

sources:
- kind: git_repo
  url: github:OpenPrinting/libcupsfilters.git
  track: '*.*.*'
  exclude:
  - '*rc*'
- kind: patch
  path: files/patches/libcupsfilters-flush-temp-pdf.patch
