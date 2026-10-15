# SPDX-License-Identifier: MIT

kind: stack
description: |
  Temporary toolbox for FDSDK integration commands (update-ca-trust, cracklib), which
  assume coreutils and gzip. It is composed into image/root-virt-tree.bst so integration can run,
  and image/root-virt.bst removes every file it added: coreutils stays out of the base
  (docs/spec.md §5.2, §7.2).

depends:
- junctions/freedesktop-sdk.bst:bootstrap/coreutils.bst
- junctions/freedesktop-sdk.bst:bootstrap/gzip.bst
