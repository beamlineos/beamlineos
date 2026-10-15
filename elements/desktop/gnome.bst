# SPDX-License-Identifier: MIT

kind: stack
description: |
  Content of the desktop-gnome extension (docs/spec.md §7.1, §9): GNOME Shell and GDM,
  core services, Settings, Nautilus and Software, PipeWire, portals, Mesa and Flatpak.
  Terminals, the archive manager and other utilities come from Flatpak; Nautilus compresses
  and extracts archives itself (decisions D71). Left out: gnome-console, orca, rygel,
  remote desktop, user share, tour, initial setup, yelp.

depends:
- desktop/gnome-config.bst
- junctions/gnome-build-meta.bst:core/gdm.bst
- junctions/gnome-build-meta.bst:core/gnome-shell.bst
- junctions/gnome-build-meta.bst:core/mutter.bst
- junctions/gnome-build-meta.bst:core/gnome-session.bst
- junctions/gnome-build-meta.bst:core/gnome-settings-daemon.bst
- junctions/gnome-build-meta.bst:core/gnome-control-center.bst
- junctions/gnome-build-meta.bst:core/nautilus.bst
- junctions/gnome-build-meta.bst:core/gnome-software.bst
- junctions/gnome-build-meta.bst:core/gvfs-daemon.bst
- junctions/gnome-build-meta.bst:core/gnome-backgrounds.bst
- junctions/gnome-build-meta.bst:freedesktop-sdk-extra.bst:components/accountsservice.bst
- junctions/gnome-build-meta.bst:core-deps/upower.bst
- junctions/gnome-build-meta.bst:core-deps/dconf.bst
- junctions/gnome-build-meta.bst:core-deps/power-profiles-daemon.bst
- junctions/gnome-build-meta.bst:core-deps/oo7-daemon.bst
- junctions/gnome-build-meta.bst:core-deps/oo7-pam.bst
- junctions/gnome-build-meta.bst:core-deps/oo7-portal.bst
- junctions/gnome-build-meta.bst:core-deps/xdg-desktop-portal-gnome.bst
- junctions/gnome-build-meta.bst:core-deps/xdg-desktop-portal-gtk.bst
- junctions/gnome-build-meta.bst:core-deps/xdg-user-dirs-gtk.bst
- junctions/gnome-build-meta.bst:sdk/adwaita-icon-theme.bst
- junctions/gnome-build-meta.bst:sdk/adwaita-fonts.bst
- junctions/gnome-build-meta.bst:sdk/cantarell-fonts.bst
- junctions/gnome-build-meta.bst:sdk/gsettings-desktop-schemas.bst
- junctions/gnome-build-meta.bst:sdk/glib-networking.bst
# update-desktop-database. GIO associates applications with MIME types and URL schemes only
# through each directory's mimeinfo.cache, never by reading MimeType= lines, and only this tool
# writes it: for /usr/share/applications through its integration command, and for Flatpak's
# exports through Flatpak's desktop-database trigger. Without it no application handles
# anything, and every Default Apps row in Settings is greyed out (0.0.4.1 K19, D84).
- junctions/freedesktop-sdk.bst:components/desktop-file-utils.bst
# GStreamer's VP8/VP9, Matroska and WebM elements: Settings' illustration videos and Shell's
# screencasts need them (0.0.4.1 K15, D84).
- junctions/freedesktop-sdk.bst:components/gstreamer-plugins-good.bst
- junctions/freedesktop-sdk.bst:components/pipewire-daemon.bst
- junctions/freedesktop-sdk.bst:components/xdg-desktop-portal.bst
- junctions/freedesktop-sdk.bst:components/flatpak.bst
- junctions/freedesktop-sdk.bst:vm/mesa-default.bst
- junctions/freedesktop-sdk.bst:vm/config/flathub.bst
- junctions/freedesktop-sdk.bst:vm/config/pipewire.bst
# gjs and mozjs link libreadline but declare no runtime dependency on it: on FDSDK 26.08,
# gbm's base, something else provides it; on FDSDK master nothing does (decisions D38).
- junctions/freedesktop-sdk.bst:bootstrap/readline.bst
