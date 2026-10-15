# SPDX-License-Identifier: MIT

kind: stack
description: |
  glibc, dynamic loader, libgcc/libstdc++ runtime and the FHS mount-point skeleton.

  FDSDK's runtime-minimal no longer carries bash or coreutils (26.08), which is what
  the base wants: nothing at runtime may assume echo, cat, grep or a bash.

depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-minimal.bst
- junctions/freedesktop-sdk.bst:vm/base-filesystem.bst
# /etc/ld.so.conf includes ld.so.conf.d/*.conf, so extensions add library paths as
# snippets (desktop-gnome's Mesa) instead of replacing the base's file (decisions D38).
- junctions/freedesktop-sdk.bst:integration/ldconfig.bst
