# SPDX-License-Identifier: MIT

kind: filter
description: |
  FDSDK's polkit daemon and agent with the interpreter-free base library closure
  (docs/spec.md §5.2, §19, D61). duktape is an embedded engine, not a user interpreter.

build-depends:
- junctions/freedesktop-sdk.bst:components/polkit.bst

runtime-depends:
- base/polkit-gobject.bst
- junctions/freedesktop-sdk.bst:components/duktape.bst
- junctions/freedesktop-sdk.bst:components/linux-pam.bst
- junctions/freedesktop-sdk.bst:components/polkit-manifest.bst

config:
  exclude:
  - debug
  - devel
  - doc
  - tests
  include-orphans: true

public:
  bst:
    overlap-whitelist:
    - '%{bindir}/pkaction'
    - '%{bindir}/pkcheck'
    - '%{bindir}/pkexec'
    - '%{bindir}/pkttyagent'
    - '%{libdir}/libpolkit-agent-1.so*'
    - '%{libdir}/girepository-1.0/PolkitAgent-1.0.typelib'
    - '%{indep-libdir}/pam.d/polkit-1'
    - '%{indep-libdir}/polkit-1/**'
    - '%{indep-libdir}/systemd/system/polkit*.service'
    - '%{indep-libdir}/systemd/system/polkit*.socket'
    - '%{indep-libdir}/sysusers.d/polkit.conf'
    - '%{indep-libdir}/tmpfiles.d/polkit-tmpfiles.conf'
    - '%{datadir}/dbus-1/system-services/org.freedesktop.PolicyKit1.service'
    - '%{datadir}/dbus-1/system.d/org.freedesktop.PolicyKit1.conf'
    - '%{datadir}/locale/*/LC_MESSAGES/polkit-1.mo'
    - '%{datadir}/polkit-1/**'
    - '%{licensedir}/freedesktop-sdk/polkit/**'
