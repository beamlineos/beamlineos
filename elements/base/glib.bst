# SPDX-License-Identifier: MIT

kind: stack
description: |
  GLib's compiled runtime and libraries, without Python or python3-packaging
  (docs/spec.md §5.2, D61). sysprof's capture library is statically linked into GLib.

depends:
- base/glib-files.bst
- junctions/freedesktop-sdk.bst:public-stacks/runtime-minimal.bst
- junctions/freedesktop-sdk.bst:components/libffi.bst
- junctions/freedesktop-sdk.bst:components/util-linux.bst
