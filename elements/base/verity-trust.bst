# SPDX-License-Identifier: MIT

kind: manual
description: |
  The certificate systemd verifies extension images' verity signatures against
  (docs/spec.md §8, docs/decisions.md D50): /usr/lib/verity.d, one of systemd's verity.d
  search paths, so the trust is part of SYSTEM. The development certificate until production
  keys exist (docs/security.md §19.4). Only the certificate: the key stays build-only.

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-gnu.bst

variables:
  strip-binaries: ''

config:
  install-commands:
  - install -Dm644 verity.crt "%{install-root}%{indep-libdir}/verity.d/%{os-id}-development.crt"

sources:
- kind: local
  path: files/keys/dev/verity/verity.crt
