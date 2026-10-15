# SPDX-License-Identifier: MIT
kind: autotools
description: GNU time from its designated HEAD
build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/buildsystem-autotools.bst
- junctions/freedesktop-sdk.bst:components/gettext.bst
- junctions/freedesktop-sdk.bst:components/texinfo.bst
- junctions/freedesktop-sdk.bst:components/gperf.bst
- junctions/freedesktop-sdk.bst:components/python3.bst
depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-minimal.bst
variables:
  conf-local: --prefix=%{prefix} --libdir=%{libdir}
config:
  configure-commands:
    (<):
    - printf '1.10+git\n' > .tarball-version
    - sh ./bootstrap --no-git --no-bootstrap-sync --skip-po --gnulib-srcdir=gnulib
  build-commands:
    (>):
    - make check
sources:
- kind: git
  url: savannah:time.git
  track: master
  ref-format: git-describe
  submodules:
    gnulib:
      url: savannah:gnulib.git
