# SPDX-License-Identifier: MIT

kind: script
description: |
  The desktop-gnome system extension and confext images (docs/spec.md §7.1, §8;
  docs/decisions.md D38), merged automatically from DATA. Unit enablement comes from
  presets applied at build time.

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
- printing-scanning/desktop-exclusions.bst
- desktop/pruned-exclusions.bst
- filename: extensions/desktop-gnome-tree.bst
  config:
    location: /tree
- filename: image/root-virt.bst
  config:
    location: /base
- filename: desktop/gnome.bst
  config:
    location: /reference/content
- filename: image/integration-tools.bst
  config:
    location: /reference/tools

variables:
  extension-name: desktop-gnome
  extension-presets: 'true'
  extension-prune: >-
    %{image-tools}/prune/base.txt
    %{image-tools}/prune/base-devel.txt
    %{image-tools}/prune/desktop-gnome.txt
  extension-package-excludes: >-
    --exclude-from %{image-tools}/printing-desktop-exclusions.txt
    --exclude-from %{image-tools}/desktop-pruned-exclusions.txt
  # Keep embedded Lua and gjs for Shell's native D-Bus helper services (D66).
  extension-extra-excludes: >-
    --exclude %{bindir}/lua --exclude %{bindir}/luac --exclude %{bindir}/wpexec
    --exclude %{bindir}/gjs-console
    --exclude %{bindir}/nmcli --exclude %{bindir}/nm-online
    --exclude %{indep-libdir}/systemd/system/NetworkManager-wait-online.service

config:
  commands:
    (<):
    - |
      # Upstream gjs is an alias to gjs-console. Retain the same binary as gjs alone;
      # the Shell's three remaining D-Bus helpers require that command (D66).
      test "$(readlink /tree%{bindir}/gjs)" = gjs-console
      rm /tree%{bindir}/gjs
      mv /tree%{bindir}/gjs-console /tree%{bindir}/gjs
    - |
      # Remove package files before presets, so their units cannot be enabled (D65, D67).
      python3 - <<'PYCODE'
      import os
      for listing in ("printing-desktop-exclusions.txt", "desktop-pruned-exclusions.txt"):
          with open("%{image-tools}/" + listing) as stream:
              for line in stream:
                  path = line.split("#", 1)[0].strip()
                  if path and os.path.lexists("/tree" + path):
                      os.unlink("/tree" + path)
      for path in ("/usr/bin/nmcli", "/usr/bin/nm-online",
                   "/usr/lib/systemd/system/NetworkManager-wait-online.service"):
          if os.path.lexists("/tree" + path):
              os.unlink("/tree" + path)
      PYCODE
    (>):
    - |
      test ! -e "%{image-scratch}/sysext/usr/bin/cupsd"
      test ! -e "%{image-scratch}/sysext/usr/bin/lp"
      test ! -e "%{image-scratch}/sysext/usr/bin/scanimage"
      test ! -e "%{image-scratch}/confext/etc/cups/cupsd.conf"
      test -e "%{image-scratch}/sysext%{libdir}/libcups.so.2"
      # The base's linker cache covers the extensions; one shipped here would hide Mesa's
      # libraries again whenever another extension is merged (D82).
      test ! -e "%{image-scratch}/confext/etc/ld.so.cache"
      test ! -e "%{image-scratch}/sysext%{bindir}/gnome-extensions"
      # The archive manager is a Flatpak application; Nautilus handles archives itself (D71).
      test ! -e "%{image-scratch}/sysext%{bindir}/file-roller"
      test -x "%{image-scratch}/sysext%{bindir}/nautilus"
      test ! -e "%{image-scratch}/sysext%{bindir}/lua"
      test ! -e "%{image-scratch}/sysext%{bindir}/wpexec"
      test ! -e "%{image-scratch}/sysext%{bindir}/gjs-console"
      test -x "%{image-scratch}/sysext%{bindir}/gjs"
      test ! -e "%{image-scratch}/sysext%{datadir}/dbus-1/services/org.gnome.Shell.Extensions.service"
      for command in sshd lvm iptables ip6tables plymouth pppd nmcli nm-online lvm-cache-stats; do
        test ! -e "%{image-scratch}/sysext%{bindir}/${command}"
      done
      test ! -e "%{image-scratch}/sysext%{libexecdir}/sshd-auth"
      test ! -e "%{image-scratch}/sysext%{libexecdir}/sshd-session"
      test -x /base%{bindir}/dmsetup
      test -e /base%{indep-libdir}/udev/rules.d/10-dm.rules
      # Pruned in 0.0.4.2 step 2A (D88): Samba keeps only its client library; Python, the daemons of
      # NetworkManager, BlueZ and fwupd, and GNU sed leave; Mesa keeps what Virt uses.
      test ! -e "%{image-scratch}/sysext%{bindir}/smbd"
      test -e "%{image-scratch}/sysext%{libdir}/libsmbclient.so.0"
      test ! -e "%{image-scratch}/sysext%{bindir}/python3"
      test ! -d "%{image-scratch}/sysext%{indep-libdir}/python3.14"
      test ! -e "%{image-scratch}/sysext%{bindir}/NetworkManager"
      test -e "%{image-scratch}/sysext%{libdir}/libnm.so.0"
      test ! -e "%{image-scratch}/sysext%{libexecdir}/bluetooth/bluetoothd"
      test ! -e "%{image-scratch}/sysext%{libexecdir}/fwupd/fwupd"
      test ! -e "%{image-scratch}/sysext%{bindir}/sed"
      test -e "%{image-scratch}/sysext%{libdir}/GL/default/lib/libvulkan_lvp.so"
      test ! -e "%{image-scratch}/sysext%{libdir}/GL/default/lib/libvulkan_radeon.so"
      test -n "$(ls "%{image-scratch}/sysext%{libdir}"/GL/default/lib/libgallium-*.so)"
      # 2B (D89): Settings without parental controls; no GVfs admin backend, no SSH server traces.
      test -z "$(ls "%{image-scratch}/sysext%{libdir}"/libmalcontent* 2>/dev/null)"
      test ! -e "%{image-scratch}/sysext%{libexecdir}/gvfsd-admin"
      test ! -e "%{image-scratch}/sysext%{datadir}/polkit-1/actions/org.gnome.controlcenter.remote-login-helper.policy"
      test -x "%{image-scratch}/sysext%{bindir}/gnome-control-center"
