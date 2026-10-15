# SPDX-License-Identifier: MIT

kind: manual
description: |
  /usr/lib/os-release rendered from project.conf identity variables. IMAGE_VERSION is the
  snapshot identifier (§17.2). ID, SYSEXT_LEVEL/CONFEXT_LEVEL (the snapshot identifier too)
  and ARCHITECTURE are the extension compatibility keys (docs/spec.md §8, decisions D50).

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
- junctions/freedesktop-sdk.bst:bootstrap/sed.bst

variables:
  strip-binaries: ''
  (?):
  - arch == "aarch64":
      os-release-arch: arm64
  - arch == "x86_64":
      os-release-arch: x86-64

config:
  install-commands:
  - |
    sed -e 's|@OS_ID@|%{os-id}|g' \
        -e 's|@OS_NAME@|%{os-name}|g' \
        -e 's|@OS_VERSION@|%{os-version}|g' \
        -e 's|@SNAPSHOT@|%{snapshot-id}|g' \
        -e 's|@ARCHITECTURE@|%{os-release-arch}|g' \
        os-release.in > os-release
    install -Dm644 os-release "%{install-root}%{indep-libdir}/os-release"
    install -d "%{install-root}%{sysconfdir}"
    ln -s ../usr/lib/os-release "%{install-root}%{sysconfdir}/os-release"

sources:
- kind: local
  path: files/base/os-release.in
