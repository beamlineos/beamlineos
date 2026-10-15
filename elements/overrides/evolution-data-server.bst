# SPDX-License-Identifier: MIT
#
# Override of gnome-build-meta core-deps/evolution-data-server.bst without WebKitGTK
# (docs/spec.md §7.1, docs/decisions.md D29): its GTK4 OAuth2 sign-in window is the only
# path to WebKitGTK and JavaScriptCoreGTK in the desktop. GNOME Online Accounts signs in
# through the browser instead.
#
# Copied from: gnome-build-meta f871a508609cced5e6607f9518b018084c558149
#   elements/core-deps/evolution-data-server.bst
# Changes from the original: the source ref lives in project.refs (ref-storage),
# dependencies carry junction prefixes, gbm's recc include is replaced by its gcc
# dependency (recc is passthrough here), sdk/webkitgtk.bst is dropped and
# -DENABLE_OAUTH2_WEBKITGTK4=OFF is added.

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
