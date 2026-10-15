# SPDX-License-Identifier: MIT

kind: script
description: |
  The posix system extension image, plus a confext when it carries /etc content
  (docs/spec.md §7.2, docs/decisions.md D36). Activated on demand by
  `beamlinectl activate posix`, or persistently with `beamlinectl enable posix`.

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
- filename: extensions/posix-tree.bst
  config:
    location: /tree
- filename: image/root-virt.bst
  config:
    location: /base
- filename: posix/posix.bst
  config:
    location: /reference/content
- filename: image/integration-tools.bst
  config:
    location: /reference/tools

variables:
  extension-name: posix
  extension-posix-scope: posix
  extension-moved-tools: ''
