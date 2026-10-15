# SPDX-License-Identifier: MIT

kind: manual
description: |
  The Beamline SELinux policy (docs/security.md §7, §16; docs/decisions.md D35): CIL from
  files/selinux plus the kernel-defined part generated from kernel/selinux-headers.bst,
  compiled with secilc (MCS) and validated with setfiles. Installs /etc/selinux: config
  (Stage 0: permissive), the binary policy, file contexts, default contexts, the bus's
  dbus_contexts and seusers.

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
- junctions/freedesktop-sdk.bst:components/python3.bst
- security/selinux-tools.bst
- kernel/selinux-headers.bst

variables:
  strip-binaries: ''
  selinux-type: beamline
  policy-dir: '%{sysconfdir}/selinux/%{selinux-type}'
  selinux-tools-dir: '%{libexecdir}/%{os-id}/selinux-tools'

config:
  build-commands:
  - |
    python3 kernel-cil.py --headers "%{includedir}/%{os-id}/kernel-selinux" \
      --out kernel.cil --policy-version-file policy-version

  - |
    version="$(cat policy-version)"
    "%{selinux-tools-dir}/secilc" --mls=true --policyvers="${version}" \
      --output="policy.${version}" --filecontext=file_contexts kernel.cil policy/*.cil policy/services/*.cil
    "%{selinux-tools-dir}/setfiles" -c "policy.${version}" file_contexts

  install-commands:
  - |
    version="$(cat policy-version)"
    install -Dm644 config "%{install-root}%{sysconfdir}/selinux/config"
    install -Dm644 "policy.${version}" "%{install-root}%{policy-dir}/policy/policy.${version}"
    install -Dm644 file_contexts "%{install-root}%{policy-dir}/contexts/files/file_contexts"
    install -Dm644 -t "%{install-root}%{policy-dir}/contexts" \
      contexts/default_contexts contexts/default_type contexts/failsafe_context \
      contexts/dbus_contexts
    install -Dm644 seusers "%{install-root}%{policy-dir}/seusers"

sources:
- kind: local
  path: files/selinux
