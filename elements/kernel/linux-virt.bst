# SPDX-License-Identifier: MIT

kind: manual
description: |
  Project-owned Linux for the Virt profile (docs/spec.md §11.4): narrow (allnoconfig plus
  fragments), virtio boot path built in, module support kept, LLVM toolchain, Linux
  master resolved by the integration cycle. Modules must be signed: the committed
  development key is staged as certs/module-signing.pem (docs/security.md §19.4). The
  development verity certificate, certs/verity.crt, joins the built-in trusted keyring, so
  the kernel checks extension images' signatures (docs/decisions.md D53). IPE's boot policy,
  certs/boot.pol, is compiled in (docs/decisions.md D102).

(@):
- include/kernel/linux.yml
- include/kernel/build.yml

variables:
  kernel-profile: virt
  kernel-base: allnoconfig

sources:
  (>):
  - kind: local
    path: files/keys/dev/kernel-modules/module-signing.pem
    directory: certs
  - kind: local
    path: files/keys/dev/verity/verity.crt
    directory: certs
  - kind: local
    path: files/kernel/ipe/boot.pol
    directory: certs
