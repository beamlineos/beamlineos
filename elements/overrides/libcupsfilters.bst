# SPDX-FileCopyrightText: Freedesktop-SDK Developers
# SPDX-License-Identifier: MIT








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
