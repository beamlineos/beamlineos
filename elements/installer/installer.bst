# SPDX-License-Identifier: MIT

kind: stack
description: |
  Everything only an installation needs (docs/decisions.md D113), shipped by the installer
  extension and never by SYSTEM: systemd-sysinstall (part of systemd's build, which the base prunes
  it from: policy/base-installer.txt), its partition definitions and units, the target ESP's boot
  chain, and dosfstools, with which repart formats the target's ESP and XBOOTLDR.

depends:
- installer/config.bst
- installer/esp.bst
- junctions/freedesktop-sdk.bst:components/dosfstools.bst
