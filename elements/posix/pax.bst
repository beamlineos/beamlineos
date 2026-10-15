# SPDX-License-Identifier: MIT
# Canonical maintainer source, with no accessible Git HEAD (D63).
kind: manual
description: paxmirabilis, the POSIX archive utility
build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/buildsystem-autotools.bst
depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-minimal.bst
config:
  build-commands:
  - sh Build.sh -r -tpax
  - |
    mkdir -p /tmp/pax-in /tmp/pax-out
    printf 'Beamline archive round trip\n' > /tmp/pax-in/sample
    pax_binary="$(pwd)/pax"
    (cd /tmp/pax-in && "$pax_binary" -w -x ustar sample > /tmp/pax-test)
    (cd /tmp/pax-out && "$pax_binary" -r < /tmp/pax-test)
    cmp /tmp/pax-in/sample /tmp/pax-out/sample
  install-commands:
  - install -Dm755 pax "%{install-root}%{bindir}/pax"
  - install -Dm644 pax.1 "%{install-root}%{datadir}/man/man1/pax.1"
sources:
- kind: tar
  url: mirbsd:paxmirabilis-20201030.tgz
