# SPDX-License-Identifier: MIT

kind: script
description: |
  The sysusers.d files printing-scanning brings. The SYSTEM image creates these users when it
  is built (image/root-virt.bst), because /etc is read-only and required fixed identities
  belong to the base release definition (docs/spec.md §14, §18.2; docs/decisions.md D38).

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
# cmp: runtime-gnu has no diffutils. Without it every comparison failed and the base's own
# files were borrowed too (found in 0.0.4.2 step 1).
- junctions/freedesktop-sdk.bst:bootstrap/diffutils.bst
# The extension's prune lists (D88): users of removed services are not created.
- junctions/freedesktop-sdk.bst:components/python3.bst
- image/image-tools.bst
- filename: extensions/printing-scanning-tree.bst
  config:
    location: /tree
- filename: profiles/virt.bst
  config:
    location: /base

variables:
  extension-sysusers-dir: '%{datadir}/%{os-id}/extension-sysusers/printing-scanning'

config:
  commands:
  - |
    python3 "%{libexecdir}/%{os-id}-image-tools/prune-tree.py" --tree /tree \
      "%{libexecdir}/%{os-id}-image-tools/prune/base.txt" \
      "%{libexecdir}/%{os-id}-image-tools/prune/base-devel.txt" \
      "%{libexecdir}/%{os-id}-image-tools/prune/printing-scanning.txt"
    install -d "%{install-root}%{extension-sysusers-dir}"
    for conf in /tree/usr/lib/sysusers.d/*.conf; do
      name="$(basename "${conf}")"
      if [ -e "/base/usr/lib/sysusers.d/${name}" ] && cmp -s "${conf}" "/base/usr/lib/sysusers.d/${name}"; then
        continue
      fi
      install -m644 "${conf}" "%{install-root}%{extension-sysusers-dir}/${name}"
    done
    ls "%{install-root}%{extension-sysusers-dir}"
