# SPDX-License-Identifier: MIT

kind: filter
description: |
  GLib's runtime files without its dependency closure (docs/spec.md §5.2, D61).
  base/glib-files.bst removes the developer tools that require Python.

build-depends:
- junctions/gnome-build-meta.bst:sdk/glib.bst

config:
  exclude:
  - debug
  - devel
  - doc
  include-orphans: true
