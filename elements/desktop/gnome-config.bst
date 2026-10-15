# SPDX-License-Identifier: MIT

kind: import
description: |
  desktop-gnome configuration (docs/decisions.md D38, D54, D96): GDM's settings (no automatic
  login: homed needs the password), gbm's GDM login and greeter stacks with pam_selinux added,
  the display-manager alias and the desktop presets. Its /etc content ships in the
  desktop-gnome confext. The GDM dependency stages this element after the files it replaces.

depends:
- desktop/gnome-session-entry.bst
- junctions/gnome-build-meta.bst:core/gdm.bst

public:
  bst:
    overlap-whitelist:
    - '%{sysconfdir}/gdm/custom.conf'
    - '%{sysconfdir}/pam.d/gdm-autologin'
    - '%{sysconfdir}/pam.d/gdm-launch-environment'
    - '%{sysconfdir}/pam.d/gdm-password'

sources:
- kind: local
  path: files/desktop/gnome
