# SPDX-License-Identifier: MIT










kind: junction

sources:
- kind: git_repo
  url: gitlab:freedesktop-sdk/freedesktop-sdk.git
  track: master

config:
  options:
    target_arch: '%{arch}'
    bootstrap_build_arch: '%{arch}'

  
  
  overrides:
    components/_private/systemd-base.bst: overrides/systemd-base.bst
    components/systemd.bst: overrides/systemd.bst
    components/linux-pam-base.bst: overrides/linux-pam-base.bst
    components/dbus-broker.bst: overrides/dbus-broker.bst
    components/erofs-utils.bst: overrides/erofs-utils.bst
    components/fuse3.bst: overrides/fuse3.bst
    components/libcupsfilters.bst: overrides/libcupsfilters.bst

    
    
    
    
    
    components/at-spi2-core.bst: junctions/gnome-build-meta.bst:sdk/at-spi2-core.bst
    components/cairo.bst: junctions/gnome-build-meta.bst:sdk/cairo.bst
    components/fcitx5-gtk.bst: junctions/gnome-build-meta.bst:sdk/fcitx5-gtk.bst
    components/gcab.bst: junctions/gnome-build-meta.bst:sdk/gcab.bst
    components/gdk-pixbuf.bst: junctions/gnome-build-meta.bst:sdk/gdk-pixbuf.bst
    components/glib-networking.bst: junctions/gnome-build-meta.bst:sdk/glib-networking.bst
    components/glib.bst: junctions/gnome-build-meta.bst:sdk/glib.bst
    components/glycin.bst: junctions/gnome-build-meta.bst:sdk/glycin.bst
    components/gobject-introspection.bst: junctions/gnome-build-meta.bst:sdk/gobject-introspection.bst
    components/python3-gi-docgen.bst: junctions/gnome-build-meta.bst:sdk/gi-docgen.bst
    components/graphene.bst: junctions/gnome-build-meta.bst:sdk/graphene.bst
    components/gsettings-desktop-schemas.bst: junctions/gnome-build-meta.bst:sdk/gsettings-desktop-schemas.bst
    components/gtk3.bst: junctions/gnome-build-meta.bst:sdk/gtk+-3.bst
    components/libibus.bst: junctions/gnome-build-meta.bst:sdk/libibus.bst
    components/json-glib.bst: junctions/gnome-build-meta.bst:sdk/json-glib.bst
    components/libglycin.bst: junctions/gnome-build-meta.bst:sdk/libglycin.bst
    components/libnotify.bst: junctions/gnome-build-meta.bst:sdk/libnotify.bst
    components/librsvg.bst: junctions/gnome-build-meta.bst:sdk/librsvg.bst
    components/libsoup.bst: junctions/gnome-build-meta.bst:sdk/libsoup.bst
    components/pango.bst: junctions/gnome-build-meta.bst:sdk/pango.bst
    components/pygobject.bst: junctions/gnome-build-meta.bst:sdk/pygobject.bst
    components/vala.bst: junctions/gnome-build-meta.bst:sdk/vala.bst
    components/libsecret.bst: junctions/gnome-build-meta.bst:sdk/libsecret.bst
    components/zenity.bst: junctions/gnome-build-meta.bst:void/zenity.bst
    components/_private/xdg-desktop-portal-base.bst: junctions/gnome-build-meta.bst:core-deps/xdg-desktop-portal-base.bst
    components/xdg-desktop-portal.bst: junctions/gnome-build-meta.bst:core-deps/xdg-desktop-portal.bst
    components/flatpak.bst: junctions/gnome-build-meta.bst:core-deps/flatpak.bst
    components/libical.bst: junctions/gnome-build-meta.bst:core-deps/libical3.bst
    components/krb5.bst: junctions/gnome-build-meta.bst:sdk/krb5.bst
    
