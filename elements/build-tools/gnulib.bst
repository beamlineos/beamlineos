# SPDX-License-Identifier: MIT
kind: import
description: GNU build-only portability library at its designated HEAD (D63)
config:
  target: /usr/share/beamline/gnulib
sources:
- kind: git
  url: savannah:gnulib.git
  track: master
  ref-format: git-describe
