# SPDX-License-Identifier: MIT

kind: manual
description: |
  Launch GNOME directly, without re-executing the user's login shell with -c.
  beamline-shell deliberately refuses that interpreter use (§6, D62). Preserve the
  upstream session entry and translations, changing only its supported launch option.

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
- junctions/gnome-build-meta.bst:core/gnome-session.bst

runtime-depends:
- junctions/gnome-build-meta.bst:core/gnome-session.bst

variables:
  strip-binaries: ''

config:
  install-commands:
  - |
    entry="%{install-root}%{datadir}/wayland-sessions/gnome.desktop"
    install -Dm644 %{datadir}/wayland-sessions/gnome.desktop "${entry}"
    sed -i 's|^Exec=/usr/bin/gnome-session$|Exec=/usr/bin/gnome-session --no-reexec|' "${entry}"
    grep -Fx 'Exec=/usr/bin/gnome-session --no-reexec' "${entry}"

public:
  bst:
    overlap-whitelist:
    - '%{datadir}/wayland-sessions/gnome.desktop'
