# SPDX-License-Identifier: MIT

kind: script
description: |
  The printing-scanning system and configuration extensions (§7.4, D65), enabled
  on demand by an administrator. CUPS state lives on DATA (D58); HPLIP is excluded (D64).

(@):
- include/extension.yml

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
- junctions/freedesktop-sdk.bst:components/python3.bst
- junctions/freedesktop-sdk.bst:components/erofs-utils.bst
- image/repart-extension.bst
- security/keys-verity.bst
- junctions/freedesktop-sdk.bst:components/systemd.bst
- image/image-tools.bst
- image/permissions.bst
- filename: extensions/printing-scanning-tree.bst
  config:
    location: /tree
- filename: image/root-virt.bst
  config:
    location: /base
- filename: printing-scanning/printing-scanning.bst
  config:
    location: /reference/content
- filename: image/integration-tools.bst
  config:
    location: /reference/tools

variables:
  extension-name: printing-scanning
  extension-presets: 'false'
  extension-prune: >-
    %{image-tools}/prune/base.txt
    %{image-tools}/prune/base-devel.txt
    %{image-tools}/prune/printing-scanning.txt

config:
  commands:
    (>):
    - |
      test -x "%{image-scratch}/sysext/usr/bin/cupsd"
      test -x "%{image-scratch}/sysext/usr/bin/lp"
      test -x "%{image-scratch}/sysext/usr/bin/scanimage"
      test ! -e "%{image-scratch}/sysext/usr/lib/cups/backend/hp"
      test ! -e "%{image-scratch}/sysext/usr/bin/hp-setup"
