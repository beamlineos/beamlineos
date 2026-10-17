# SPDX-License-Identifier: MIT

kind: script
description: |
  The installer system extension (docs/decisions.md D113): systemd-sysinstall, the installer's
  units and partition definitions, the target ESP's boot chain and dosfstools. Only the installer
  medium carries it, beside the installer UKI; the medium's initrd merges it into SYSTEM's /usr
  before PID 1 starts. Never in the update channel, never on an installed disk.

(@):
- include/extension.yml

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
- junctions/freedesktop-sdk.bst:components/python3.bst
- junctions/freedesktop-sdk.bst:components/erofs-utils.bst
- junctions/freedesktop-sdk.bst:components/systemd.bst
- image/repart-extension.bst
- security/keys-verity.bst
- image/image-tools.bst
- image/permissions.bst
- filename: extensions/installer-tree.bst
  config:
    location: /tree
- filename: image/root-virt.bst
  config:
    location: /base
- filename: installer/installer.bst
  config:
    location: /reference/content
- filename: image/integration-tools.bst
  config:
    location: /reference/tools

variables:
  extension-name: installer
  
  extension-installer-files: ''
