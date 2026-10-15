# SPDX-License-Identifier: MIT

kind: filter
description: |
  FDSDK's polkit-gobject files with the interpreter-free GLib runtime (D61).
  The original artifact remains available to build and desktop dependencies.

build-depends:
- junctions/freedesktop-sdk.bst:components/polkit-gobject.bst

runtime-depends:
- base/glib.bst
- junctions/freedesktop-sdk.bst:components/polkit-manifest.bst
- junctions/freedesktop-sdk.bst:components/systemd-libs.bst

config:
  exclude:
  - debug
  - devel
  - doc
  - tests
  include-orphans: true

public:
  bst:
    overlap-whitelist:
    - '%{libdir}/libpolkit-gobject-1.so.*'
    - '%{libdir}/girepository-1.0/Polkit-1.0.typelib'
    - '%{datadir}/gettext/its/polkit.*'
