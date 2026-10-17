# SPDX-License-Identifier: MIT

kind: stack
description: |
  systemd (init, udev, journald, logind, networkd, resolved, timesyncd, repart,
  sysext, ...) and kmod. Version follows FDSDK until an override is needed
  (docs/spec.md §2.2: source-ref override first, element override second).

depends:
- junctions/freedesktop-sdk.bst:components/systemd.bst
- junctions/freedesktop-sdk.bst:components/kmod.bst

- junctions/freedesktop-sdk.bst:bootstrap/acl.bst

- base/device-mapper.bst

- base/gpg.bst

- junctions/freedesktop-sdk.bst:components/btrfs-progs.bst


- junctions/freedesktop-sdk.bst:components/tpm2-tss.bst
