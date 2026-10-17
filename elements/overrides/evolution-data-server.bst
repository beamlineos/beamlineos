# SPDX-License-Identifier: MIT













kind: cmake

sources:
- kind: git_repo
  url: gnome:evolution-data-server.git
  track: master

build-depends:
- junctions/freedesktop-sdk.bst:components/gcc.bst
- junctions/gnome-build-meta.bst:buildsystems/cmake.bst
- junctions/gnome-build-meta.bst:sdk/gobject-introspection.bst
- junctions/gnome-build-meta.bst:sdk/vala.bst
- junctions/freedesktop-sdk.bst:components/gperf.bst

depends:
- junctions/gnome-build-meta.bst:core-deps/gnome-online-accounts.bst
- junctions/gnome-build-meta.bst:core-deps/libcanberra.bst
- junctions/gnome-build-meta.bst:core-deps/libgweather.bst
- junctions/gnome-build-meta.bst:freedesktop-sdk-extra.bst:components/openldap.bst
- junctions/gnome-build-meta.bst:sdk/gcr.bst
- junctions/gnome-build-meta.bst:sdk/gtk+-3.bst
- junctions/gnome-build-meta.bst:sdk/gtk.bst
- junctions/gnome-build-meta.bst:sdk/libsecret.bst
- junctions/gnome-build-meta.bst:sdk/libsoup.bst
- junctions/freedesktop-sdk.bst:components/libical.bst
- junctions/freedesktop-sdk.bst:components/nspr.bst
- junctions/freedesktop-sdk.bst:components/nss.bst
- junctions/freedesktop-sdk.bst:public-stacks/runtime-minimal.bst

variables:
  cmake-local: >-
    -DLIB_INSTALL_DIR=%{libdir}
    -DSYSCONF_INSTALL_DIR=%{sysconfdir}
    -DENABLE_GTK=ON
    -DENABLE_OAUTH2_WEBKITGTK=OFF
    -DENABLE_OAUTH2_WEBKITGTK4=OFF
    -DENABLE_GTK4=ON
    -DENABLE_INTROSPECTION=ON
    -DENABLE_VALA_BINDINGS=ON
    -DENABLE_UOA=OFF
    -DENABLE_GOOGLE_AUTH=OFF
    -DWITH_GWEATHER4=ON
    -DWITH_LIBDB=OFF
    -DENABLE_GOOGLE=OFF
