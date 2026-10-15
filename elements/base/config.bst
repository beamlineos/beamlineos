# SPDX-License-Identifier: MIT

kind: import
description: |
  Project-owned base configuration: units, presets, journald settings, tmpfiles rules and
  the few /etc files the OS needs before confext exists (docs/spec.md §14). The login PAM
  stack replaces shadow's, which lacks pam_selinux (docs/decisions.md D30); depending on
  shadow stages this element after it.

depends:
- junctions/freedesktop-sdk.bst:components/shadow.bst

public:
  bst:
    overlap-whitelist:
    - '%{sysconfdir}/pam.d/login'

sources:
- kind: local
  path: files/base/beamline
  directory: usr/lib/beamline
- kind: local
  path: files/base/systemd
  directory: usr/lib/systemd
- kind: local
  path: files/base/tmpfiles.d
  directory: usr/lib/tmpfiles.d
- kind: local
  path: files/base/etc
  directory: etc
- kind: local
  path: files/base/pam.d
  directory: etc/pam.d
- kind: local
  path: files/base/sysupdate.d
  directory: usr/lib/sysupdate.d
- kind: local
  path: files/base/sysusers.d
  directory: usr/lib/sysusers.d
- kind: local
  path: files/base/polkit-1
  directory: usr/share/polkit-1
- kind: local
  path: files/base/udev
  directory: usr/lib/udev
