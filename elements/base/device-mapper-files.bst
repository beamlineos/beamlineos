# SPDX-License-Identifier: MIT

kind: script
description: |
  dmsetup and device-mapper's udev rules, copied out of FDSDK's lvm2 (docs/decisions.md
  D47). systemd-veritysetup activates SYSTEM through libdevmapper, which waits for udev to
  confirm each device; without these rules nothing confirms, and nothing names
  /dev/mapper/root. FDSDK defines no split domain for them, and the rest of lvm2 (LVM
  itself) has no use in the base. base/device-mapper.bst adds the runtime dependency.

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
- filename: junctions/freedesktop-sdk.bst:components/lvm2.bst
  config:
    location: /input

config:
  commands:
  - |
    install -Dm755 -t "%{install-root}%{bindir}" "/input%{bindir}/dmsetup"
    for rules in 10-dm.rules 13-dm-disk.rules 95-dm-notify.rules; do
      install -Dm644 -t "%{install-root}%{indep-libdir}/udev/rules.d" \
        "/input%{indep-libdir}/udev/rules.d/${rules}"
    done

public:
  bst:
    # Trees that also contain FDSDK's whole lvm2 (desktop-gnome, through udisks) carry these
    # same files from it; the copies are identical.
    overlap-whitelist:
    - '%{bindir}/dmsetup'
    - '%{indep-libdir}/udev/rules.d/10-dm.rules'
    - '%{indep-libdir}/udev/rules.d/13-dm-disk.rules'
    - '%{indep-libdir}/udev/rules.d/95-dm-notify.rules'
