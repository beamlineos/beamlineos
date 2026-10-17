# SPDX-License-Identifier: MIT









kind: meson

sources:
- kind: git_repo
  url: gnome:gdm.git
  track: main
- kind: local
  path: files/gdm
  directory: gdm-config

build-depends:
- junctions/freedesktop-sdk.bst:components/gcc.bst
- junctions/gnome-build-meta.bst:buildsystems/meson.bst
- junctions/gnome-build-meta.bst:core-deps/libcheck.bst
- junctions/gnome-build-meta.bst:sdk/yelp-tools.bst

depends:
- junctions/gnome-build-meta.bst:core-deps/dconf.bst
- junctions/gnome-build-meta.bst:core-deps/libcanberra.bst
- junctions/gnome-build-meta.bst:core-deps/plymouth.bst
- junctions/gnome-build-meta.bst:core-deps/upower.bst
- junctions/gnome-build-meta.bst:sdk/glib.bst
- junctions/gnome-build-meta.bst:freedesktop-sdk-extra.bst:components/accountsservice.bst
- junctions/freedesktop-sdk.bst:bootstrap/libselinux.bst
- junctions/freedesktop-sdk.bst:public-stacks/runtime-minimal.bst

variables:
  sysusersdir: '%{prefix}/lib/sysusers.d'
  pamdir: '%{sysconfdir}/pam.d'
  meson-local: >-
    -Ddefault-pam-config=none
    -Dlibaudit=disabled
    -Dplymouth=enabled
    -Drun-dir=/run/gdm
    -Dselinux=enabled

config:
  install-commands:
    (>):
    - mkdir -p %{install-root}%{sysusersdir}
    - install -m 644 gdm-config/gdm-sysusers.conf %{install-root}%{sysusersdir}/gdm.conf

    - mkdir -p %{install-root}%{pamdir}
    - |
      
      for conffile in `find gdm-config/ -name "*.pam"`; do
        install -m 644 $conffile %{install-root}%{pamdir}/$(basename ${conffile%.pam})
      done

    - |
      install -Dm644 -t "%{install-root}%{datadir}/glib-2.0/schemas" gdm-config/org.gnome.login-screen.gschema.override
