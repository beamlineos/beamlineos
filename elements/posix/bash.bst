# SPDX-License-Identifier: MIT

kind: stack
description: |
  bash for the posix extension (docs/spec.md §7.2): FDSDK's bash without /usr/bin/sh, so
  bash's sh link exists in no tree and /usr/bin/sh is always dash (§6, docs/decisions.md
  D37), with bash's own runtime dependency.

depends:
- posix/bash-without-sh.bst
- junctions/freedesktop-sdk.bst:bootstrap/readline.bst
