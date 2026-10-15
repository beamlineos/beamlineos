# SPDX-License-Identifier: MIT

kind: manual
description: |
  The kernel's SELinux object classes, initial SIDs and policy version
  (security/selinux/include/), from the same Linux source as the project's kernels. The
  policy generates its kernel-defined part from them (docs/decisions.md D35), so it always
  matches the kernel it ships with. Build-time only (devel domain).

(@):
- include/kernel/linux.yml

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-gnu.bst

variables:
  strip-binaries: ''

config:
  install-commands:
  - |
    install -Dm644 -t "%{install-root}%{includedir}/%{os-id}/kernel-selinux" \
      security/selinux/include/classmap.h \
      security/selinux/include/initial_sid_to_string.h \
      security/selinux/include/security.h
