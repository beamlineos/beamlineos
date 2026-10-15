# SPDX-License-Identifier: MIT

kind: script
description: |
  The gpg binary alone, copied out of FDSDK's GnuPG (docs/decisions.md D52). systemd-pull
  verifies the signed SHA256SUMS of a channel directory by running gpg; nothing in the base
  needs GnuPG's agent, dirmngr, gpgsm or its other tools. base/gpg.bst adds the libraries gpg
  links.

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
- filename: junctions/freedesktop-sdk.bst:components/gnupg.bst
  config:
    location: /input

config:
  commands:
  - install -Dm755 -t "%{install-root}%{bindir}" "/input%{bindir}/gpg"

public:
  bst:
    # Trees that also carry all of GnuPG (desktop-gnome) have the same file from it.
    overlap-whitelist:
    - '%{bindir}/gpg'
