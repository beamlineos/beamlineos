# SPDX-License-Identifier: MIT
#
# gnome-build-meta: GNOME's BuildStream project, used as a library of GNOME recipes
# (docs/spec.md §2.2, §9; docs/decisions.md D28). Tracked at `master`: integration cycles
# select the newest commit whose upstream CI pipeline passed, and GNOME component refs come
# from that commit.
#
# gbm builds against Beamline's FDSDK junction (master, with Beamline's systemd), never its
# own FDSDK selection. In return, Beamline's FDSDK junction carries gbm's FDSDK overrides
# (elements/junctions/freedesktop-sdk.bst). recc compiles locally: gbm's default sends
# compiles to GNOME's remote execution service. BuildStream plugins are Layer 0
# (docs/spec.md §31.3): gbm loads them from Beamline's pinned plugin junctions.

kind: junction

sources:
- kind: git_repo
  url: gnome_gitlab:GNOME/gnome-build-meta.git
  track: master

config:
  options:
    arch: '%{arch}'
    recc: passthrough

  overrides:
    freedesktop-sdk.bst: junctions/freedesktop-sdk.bst
    plugins/buildstream-plugins.bst: junctions/buildstream-plugins.bst
    plugins/buildstream-plugins-community.bst: junctions/buildstream-plugins-community.bst
    # No WebKitGTK in any artifact (docs/decisions.md D29)
    core-deps/evolution-data-server.bst: overrides/evolution-data-server.bst
    # Compile out Shell extension loading (0.0.4 step 5, D66).
    core/gnome-shell.bst: overrides/gnome-shell.bst
    # Settings without parental controls, and without a Secure Shell switch when no sshd exists
    # (0.0.4.2 step 2B, D89).
    core/gnome-control-center.bst: overrides/gnome-control-center.bst
    # GDM with SELinux support: the worker that unlocks the screen runs in xdm_t (D105).
    core/gdm.bst: overrides/gdm.bst
