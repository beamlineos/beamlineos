# SPDX-License-Identifier: MIT

kind: stack
description: |
  Shared POSIX utility content for the independent posix and posix-devel extensions.
  The wrappers add their respective binutils providers; neither depends on another image.

depends:


- base/base.bst
- posix/uutils-coreutils.bst
- posix/bash.bst
- posix/uutils-grep.bst
- posix/uutils-sed.bst
- posix/uutils-awk.bst
- posix/uutils-findutils.bst
- posix/procps.bst
- junctions/freedesktop-sdk.bst:components/iproute2.bst
- junctions/freedesktop-sdk.bst:components/pciutils.bst
- junctions/freedesktop-sdk.bst:components/usbutils.bst
- junctions/freedesktop-sdk.bst:components/strace.bst
- junctions/freedesktop-sdk.bst:components/curl.bst
- junctions/freedesktop-sdk.bst:components/jq.bst
- junctions/freedesktop-sdk.bst:components/less.bst
- junctions/freedesktop-sdk.bst:components/file.bst


- junctions/freedesktop-sdk.bst:components/gdbm.bst
- posix/vi.bst
- junctions/freedesktop-sdk.bst:components/e2fsprogs.bst
- junctions/freedesktop-sdk.bst:components/dosfstools.bst
- junctions/freedesktop-sdk.bst:components/erofs-utils.bst
- posix/uutils-diffutils.bst
- posix/uutils-bsdutils.bst
- posix/gettext.bst
- posix/time.bst
- posix/sharutils.bst
- posix/pax.bst
- posix/manuals.bst
- junctions/freedesktop-sdk.bst:components/mandoc.bst
- junctions/freedesktop-sdk.bst:components/bc.bst
- junctions/freedesktop-sdk.bst:components/ed.bst
- junctions/freedesktop-sdk.bst:components/m4.bst
- junctions/freedesktop-sdk.bst:components/patch.bst
