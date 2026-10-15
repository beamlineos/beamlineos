# SPDX-License-Identifier: MIT

kind: autotools
description: |
  dash as /usr/bin/sh (docs/spec.md §6). It exists for compatibility only: base units
  must not invoke it (enforced by tools/check-policy.py). FDSDK has no dash element,
  so this one is project-owned.

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/buildsystem-autotools.bst

depends:
- base/runtime.bst

environment:
  # automake 1.18's sanity check measures a 0.01 s timestamp resolution in the build
  # sandbox, but configure and its probe file can still share a timestamp there, making
  # the "newly created file is older than distributed files" check fail at random.
  # A one-second resolution makes it sleep long enough to be deterministic.
  am_cv_filesystem_timestamp_resolution: '1'

config:
  install-commands:
    (>):
    - ln -s dash "%{install-root}%{bindir}/sh"

sources:
- kind: git
  url: kernel:utils/dash/dash.git
  track: master
  ref-format: git-describe
