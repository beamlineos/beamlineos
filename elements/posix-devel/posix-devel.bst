# SPDX-License-Identifier: MIT
kind: stack
description: Independent POSIX userspace plus C/software development and native SDK tools (§7.3, D69)
depends:
# This is a content stack, never a dependency on the posix extension image.
- posix/content.bst
- junctions/freedesktop-sdk.bst:components/gcc.bst
- junctions/freedesktop-sdk.bst:components/binutils.bst
- junctions/freedesktop-sdk.bst:bootstrap/linux-headers.bst
- junctions/freedesktop-sdk.bst:bootstrap/make.bst
- junctions/freedesktop-sdk.bst:components/libfl.bst
- junctions/freedesktop-sdk.bst:components/perl.bst
- junctions/freedesktop-sdk.bst:components/pkg-config.bst
- junctions/freedesktop-sdk.bst:components/python3.bst
- junctions/freedesktop-sdk.bst:components/meson.bst
- junctions/freedesktop-sdk.bst:components/ninja.bst
- junctions/freedesktop-sdk.bst:components/gdb.bst
- posix-devel/flex-files.bst
- posix-devel/bison-files.bst
- posix-devel/xgettext.bst
- posix-devel/commands.bst
- posix-devel/ctags.bst
