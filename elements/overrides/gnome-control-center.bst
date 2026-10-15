# SPDX-License-Identifier: MIT
# Copied from: gnome-build-meta 23c598b45f510cc0bb2161b5cc06742c45bbb00b
#   elements/core/gnome-control-center.bst
# Changes: junction prefixes, local GCC instead of recc, sources inherited by integration
# (policy/tracking.toml [recipe.gnome-control-center]), built without parental controls
# (-Dmalcontent=false, no malcontent dependency; D76, D89), and a patch hiding the Secure Shell row
# when the system has no SSH server (K11, D89).

kind: meson

sources:
- kind: git_repo
  url: gnome:gnome-control-center.git
  track: main
- kind: git_module
  url: gnome:libgnome-volume-control.git
  path: subprojects/gvc
# FIXME: This needs to be kept in sync with the wrap file ideally,
# but this will do for now
# https://gitlab.gnome.org/GNOME/gnome-control-center/-/blob/main/subprojects/libgxdp.wrap
- kind: git_repo
  url: gnome:libgxdp.git
  directory: subprojects/libgxdp

- kind: patch
  path: files/patches/gnome-control-center-secure-shell-row.patch

build-depends:
- junctions/freedesktop-sdk.bst:components/gcc.bst
- junctions/gnome-build-meta.bst:buildsystems/meson.bst
- junctions/gnome-build-meta.bst:sdk/gtk-doc.bst
- junctions/gnome-build-meta.bst:sdk/blueprint-compiler.bst

runtime-depends:
- junctions/gnome-build-meta.bst:core-deps/power-profiles-daemon.bst

depends:
- junctions/gnome-build-meta.bst:core-deps/NetworkManager.bst
- junctions/gnome-build-meta.bst:core-deps/boltd.bst
- junctions/gnome-build-meta.bst:core-deps/colord-gtk.bst
- junctions/gnome-build-meta.bst:core-deps/colord.bst
- junctions/gnome-build-meta.bst:core-deps/gnome-online-accounts.bst
- junctions/gnome-build-meta.bst:core-deps/gsound.bst
- junctions/gnome-build-meta.bst:core-deps/ibus-daemon.bst
- junctions/gnome-build-meta.bst:core-deps/libgtop.bst
- junctions/gnome-build-meta.bst:core-deps/libnma.bst
- junctions/gnome-build-meta.bst:core-deps/system-config-printer.bst
- junctions/gnome-build-meta.bst:core-deps/udisks2.bst
- junctions/gnome-build-meta.bst:core-deps/upower.bst
- junctions/gnome-build-meta.bst:core/gnome-bluetooth.bst
- junctions/gnome-build-meta.bst:core/gnome-color-manager.bst
- junctions/gnome-build-meta.bst:core/gnome-desktop.bst
- junctions/gnome-build-meta.bst:core/gnome-settings-daemon.bst
- junctions/gnome-build-meta.bst:core/tecla.bst
- junctions/gnome-build-meta.bst:sdk/adwaita-icon-theme.bst
- junctions/gnome-build-meta.bst:sdk/gdk-pixbuf.bst
- junctions/gnome-build-meta.bst:sdk/glib.bst
- junctions/gnome-build-meta.bst:sdk/gsettings-desktop-schemas.bst
- junctions/gnome-build-meta.bst:sdk/gtk.bst
- junctions/gnome-build-meta.bst:sdk/libadwaita.bst
- junctions/gnome-build-meta.bst:freedesktop-sdk-extra.bst:components/accountsservice.bst
- junctions/gnome-build-meta.bst:freedesktop-sdk-extra.bst:components/samba.bst
- junctions/freedesktop-sdk.bst:components/gstreamer.bst
- junctions/freedesktop-sdk.bst:components/libwacom.bst
- junctions/freedesktop-sdk.bst:components/modemmanager.bst
- junctions/freedesktop-sdk.bst:components/pwquality.bst
- junctions/freedesktop-sdk.bst:public-stacks/runtime-minimal.bst

variables:
  meson-local: >-
    -Ddocumentation=true
    -Dmalcontent=false
