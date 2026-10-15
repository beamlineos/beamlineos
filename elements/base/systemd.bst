# SPDX-License-Identifier: MIT

kind: stack
description: |
  systemd (init, udev, journald, logind, networkd, resolved, timesyncd, repart,
  sysext, ...) and kmod. Version follows FDSDK until an override is needed
  (docs/spec.md §2.2: source-ref override first, element override second).

depends:
- junctions/freedesktop-sdk.bst:components/systemd.bst
- junctions/freedesktop-sdk.bst:components/kmod.bst
# systemd dlopen()s libacl (journal and /run ACLs); FDSDK does not declare it.
- junctions/freedesktop-sdk.bst:bootstrap/acl.bst
# systemd-veritysetup mounts SYSTEM through device-mapper (decisions D47).
- base/device-mapper.bst
# systemd-pull verifies update signatures with gpg (decisions D52).
- base/gpg.bst
# systemd-homed formats home areas as LUKS2 holding btrfs (decisions D54).
- junctions/freedesktop-sdk.bst:components/btrfs-progs.bst
# systemd dlopen()s the TPM software stack: credentials sealed with the TPM (systemd-sysinstall,
# systemd-creds) and the boot measurements need it, in the base alone (decisions D106).
- junctions/freedesktop-sdk.bst:components/tpm2-tss.bst
