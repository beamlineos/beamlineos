# SPDX-License-Identifier: MIT
# Copied from: gnome-build-meta 23c598b45f510cc0bb2161b5cc06742c45bbb00b
#   elements/core/gdm.bst
# Changes: junction prefixes, local GCC instead of recc, sources inherited by integration
# (policy/tracking.toml [recipe.gdm]; files/gdm is gnome-build-meta's files/gdm at the same commit),
# and SELinux support (-Dselinux=enabled, libselinux; D105). With it, a session's worker clears the
# exec context pam_selinux set for the session once the session has started. Without it, the worker
# that GDM starts from there to unlock the screen ran in the session's user_t and could not switch
# to the user.

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
      # Our configuration is similar to redhat but without selinux
      for conffile in `find gdm-config/ -name "*.pam"`; do
        install -m 644 $conffile %{install-root}%{pamdir}/$(basename ${conffile%.pam})
      done

    - |
      install -Dm644 -t "%{install-root}%{datadir}/glib-2.0/schemas" gdm-config/org.gnome.login-screen.gschema.override
