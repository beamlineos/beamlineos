# SPDX-License-Identifier: MIT

kind: script
description: |
  The sysusers.d files desktop-gnome brings. The SYSTEM image creates these users when it
  is built (image/root-virt.bst), because /etc is read-only and required fixed identities
  belong to the base release definition (docs/spec.md §14, §18.2; docs/decisions.md D38).

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-gnu.bst


- junctions/freedesktop-sdk.bst:bootstrap/diffutils.bst

- junctions/freedesktop-sdk.bst:components/python3.bst
- image/image-tools.bst
- filename: extensions/desktop-gnome-tree.bst
  config:
    location: /tree
- filename: profiles/virt.bst
  config:
    location: /base

variables:
  extension-sysusers-dir: '%{datadir}/%{os-id}/extension-sysusers/desktop-gnome'

config:
  commands:
  - |
    python3 "%{libexecdir}/%{os-id}-image-tools/prune-tree.py" --tree /tree \
      "%{libexecdir}/%{os-id}-image-tools/prune/base.txt" \
      "%{libexecdir}/%{os-id}-image-tools/prune/base-devel.txt" \
      "%{libexecdir}/%{os-id}-image-tools/prune/desktop-gnome.txt"
    install -d "%{install-root}%{extension-sysusers-dir}"
    for conf in /tree/usr/lib/sysusers.d/*.conf; do
      name="$(basename "${conf}")"
      if [ -e "/base/usr/lib/sysusers.d/${name}" ] && cmp -s "${conf}" "/base/usr/lib/sysusers.d/${name}"; then
        continue
      fi
      install -m644 "${conf}" "%{install-root}%{extension-sysusers-dir}/${name}"
    done
    ls "%{install-root}%{extension-sysusers-dir}"
