# SPDX-License-Identifier: MIT












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
    
    core-deps/evolution-data-server.bst: overrides/evolution-data-server.bst
    
    core/gnome-shell.bst: overrides/gnome-shell.bst
    
    
    core/gnome-control-center.bst: overrides/gnome-control-center.bst
    
    core/gdm.bst: overrides/gdm.bst
