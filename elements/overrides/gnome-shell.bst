# SPDX-License-Identifier: MIT
# Copied from: gnome-build-meta f871a508609cced5e6607f9518b018084c558149
#   elements/core/gnome-shell.bst
# Changes: junction prefixes, local GCC instead of recc, sources inherited by integration,
# and a downstream build option compiling out extension loading (D66).

kind: meson

sources:
- kind: git_repo
  url: gnome:gnome-shell.git
  track: main
# FIXME: Keep this in sync with the repo until we can use wraps as sources
# https://gitlab.gnome.org/GNOME/gnome-shell/-/blob/main/subprojects/gvc.wrap?ref_type=heads
#
# Shell dropped the git submodule and it's only using the meson wrap now
# https://gitlab.gnome.org/GNOME/gnome-shell/-/commit/5649ad6752f0d1fa6f9f580d90b3784c699e4a1f
- kind: git_repo
  url: gnome:libgnome-volume-control.git
  directory: subprojects/gvc
- kind: git_repo
  url: gnome:libshew.git
  directory: subprojects/libshew

- kind: patch
  path: files/patches/gnome-shell/disable-extensions.patch

build-depends:
- junctions/freedesktop-sdk.bst:components/gcc.bst
- junctions/gnome-build-meta.bst:buildsystems/meson.bst
- junctions/gnome-build-meta.bst:freedesktop-sdk-extra.bst:components/sassc.bst
- junctions/gnome-build-meta.bst:core-deps/jasmine-gjs.bst
- junctions/gnome-build-meta.bst:core-deps/umockdev.bst
- junctions/freedesktop-sdk.bst:components/python3-docutils.bst
- junctions/freedesktop-sdk.bst:components/perl.bst

runtime-depends:
- junctions/gnome-build-meta.bst:core-deps/libgweather.bst
- junctions/gnome-build-meta.bst:core/tecla.bst
- junctions/freedesktop-sdk.bst:components/geoclue-libs.bst

depends:
- junctions/gnome-build-meta.bst:core-deps/NetworkManager.bst
- junctions/gnome-build-meta.bst:freedesktop-sdk-extra.bst:components/accountsservice.bst
- junctions/gnome-build-meta.bst:core-deps/dconf.bst
- junctions/gnome-build-meta.bst:core-deps/evolution-data-server.bst
- junctions/gnome-build-meta.bst:core-deps/gnome-autoar.bst
- junctions/gnome-build-meta.bst:core-deps/startup-notification.bst
- junctions/gnome-build-meta.bst:core-deps/upower.bst
- junctions/gnome-build-meta.bst:core/gdm.bst
- junctions/gnome-build-meta.bst:core/gnome-bluetooth.bst
- junctions/gnome-build-meta.bst:core/gnome-desktop.bst
- junctions/gnome-build-meta.bst:core/gnome-settings-daemon.bst
- junctions/gnome-build-meta.bst:core/mutter.bst
- junctions/gnome-build-meta.bst:sdk/adwaita-icon-theme.bst
- junctions/gnome-build-meta.bst:sdk/gcr.bst
- junctions/gnome-build-meta.bst:sdk/gjs.bst
- junctions/gnome-build-meta.bst:sdk/glib.bst
- junctions/gnome-build-meta.bst:sdk/glycin.bst
- junctions/gnome-build-meta.bst:sdk/gobject-introspection.bst
- junctions/gnome-build-meta.bst:sdk/gtk.bst
- junctions/gnome-build-meta.bst:sdk/libsoup.bst
- junctions/freedesktop-sdk.bst:components/gstreamer.bst
- junctions/freedesktop-sdk.bst:components/gstreamer-plugins-base.bst
- junctions/freedesktop-sdk.bst:public-stacks/runtime-minimal.bst

variables:
  meson-local: >-
    -Dextensions=false -Dextensions_tool=false
