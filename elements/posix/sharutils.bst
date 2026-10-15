# SPDX-License-Identifier: MIT
kind: autotools
description: GNU uuencode and uudecode from sharutils HEAD, with an offline bootstrap (D63)
build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/buildsystem-autotools.bst
- junctions/freedesktop-sdk.bst:components/gettext.bst
- junctions/freedesktop-sdk.bst:components/python3.bst
- junctions/freedesktop-sdk.bst:components/texinfo.bst
- junctions/freedesktop-sdk.bst:components/which.bst
- build-tools/autogen.bst
- build-tools/gnulib.bst
depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-minimal.bst
variables:
  conf-local: >-
    --prefix=%{prefix} --libdir=%{libdir} --disable-nls
    --disable-dependency-tracking
    CFLAGS="$CFLAGS -std=gnu17"
config:
  configure-commands:
    (<):
    - python3 sharutils-bootstrap.py
    - PATH="/usr/share/beamline/gnulib:$PATH" bash ./bootstrap
    - autoreconf -fi
  install-commands:
  - install -Dm755 -t "%{install-root}%{bindir}" src/uuencode src/uudecode
  - install -Dm644 -t "%{install-root}%{datadir}/man/man1" doc/uuencode.1 doc/uudecode.1
  - |
    printf 'Beamline round trip\n' > /tmp/uu-input
    src/uuencode /tmp/uu-input /tmp/uu-output > /tmp/encoded
    src/uudecode /tmp/encoded
    cmp /tmp/uu-input /tmp/uu-output
    src/uuencode -m /tmp/uu-input /tmp/uu-output64 > /tmp/encoded64
    src/uudecode /tmp/encoded64
    cmp /tmp/uu-input /tmp/uu-output64
sources:
- kind: git
  url: savannah:sharutils.git
  track: master
  ref-format: git-describe
- kind: local
  path: files/posix/sharutils-bootstrap.py
