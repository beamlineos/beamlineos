# SPDX-License-Identifier: MIT

kind: script
description: |
  Avahi for multicast DNS and DNS-SD. The unused autoipd/dnsconfd helpers and sample SSH
  announcements leave; networkd owns address configuration and resolved owns unicast DNS.

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
- filename: base/avahi-artifact.bst
  config:
    location: /input

config:
  commands:
  - cp -a /input/. "%{install-root}/"
  - |
    rm -f "%{install-root}%{bindir}/avahi-autoipd" \
      "%{install-root}%{bindir}/avahi-dnsconfd" \
      "%{install-root}%{indep-libdir}/systemd/system/avahi-dnsconfd.service" \
      "%{install-root}%{sysconfdir}/avahi/avahi-autoipd.action" \
      "%{install-root}%{sysconfdir}/avahi/avahi-dnsconfd.action" \
      "%{install-root}%{sysconfdir}/avahi/services/ssh.service" \
      "%{install-root}%{sysconfdir}/avahi/services/sftp-ssh.service"

public:
  bst:
    overlap-whitelist:
    - '%{bindir}/avahi-*'
    - '%{libdir}/libavahi-*'
    - '%{sysconfdir}/avahi/**'
    - '%{sysconfdir}/dbus-1/system.d/avahi-dbus.conf'
    - '%{indep-libdir}/sysusers.d/avahi.conf'
    - '%{indep-libdir}/systemd/system/avahi-*'
    - '%{datadir}/dbus-1/system-services/org.freedesktop.Avahi.service'
    - '%{datadir}/licenses/**/avahi/**'
    - '%{datadir}/avahi/**'
    - '%{datadir}/dbus-1/interfaces/org.freedesktop.Avahi.*'
    - '%{datadir}/locale/*/LC_MESSAGES/avahi.mo'
