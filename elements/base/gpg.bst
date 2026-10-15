# SPDX-License-Identifier: MIT

kind: stack
description: |
  gpg for update signature verification only (docs/spec.md §5.2, §16; docs/decisions.md D52):
  the binary and the libraries it links. The base already carries zlib, bzip2, sqlite,
  libgcrypt and libgpg-error.

depends:
- base/gpg-files.bst
- junctions/freedesktop-sdk.bst:components/libgcrypt.bst
- junctions/freedesktop-sdk.bst:components/libassuan.bst
- junctions/freedesktop-sdk.bst:components/npth.bst
- junctions/freedesktop-sdk.bst:components/sqlite.bst
- junctions/freedesktop-sdk.bst:components/zlib.bst
- junctions/freedesktop-sdk.bst:bootstrap/bzip2.bst
- junctions/freedesktop-sdk.bst:bootstrap/readline.bst
