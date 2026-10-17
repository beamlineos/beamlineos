# SPDX-FileCopyrightText: Freedesktop-SDK Developers
# SPDX-License-Identifier: MIT










kind: meson

description: Linux D-Bus Message Broker

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/buildsystem-meson.bst

depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-minimal.bst
- junctions/freedesktop-sdk.bst:components/systemd.bst
- junctions/freedesktop-sdk.bst:components/audit.bst
- junctions/freedesktop-sdk.bst:bootstrap/libselinux.bst

variables:
  
  project_licensedir: '%{licensedir}/freedesktop-sdk'
  meson-local: >-
    -Dselinux=true
    -Daudit=true





sources:
- kind: git_repo
  url: github:bus1/dbus-broker.git
  track: v*
  version-guess-pattern: '(\d+)'
- kind: git_repo
  url: github:c-util/c-dvar.git
  directory: subprojects/libcdvar-1
- kind: git_repo
  url: github:c-util/c-ini.git
  directory: subprojects/libcini-1
- kind: git_repo
  url: github:c-util/c-list.git
  directory: subprojects/libclist-3
- kind: git_repo
  url: github:c-util/c-rbtree.git
  directory: subprojects/libcrbtree-3
- kind: git_repo
  url: github:c-util/c-shquote.git
  directory: subprojects/libcshquote-1
- kind: git_repo
  url: github:c-util/c-stdaux.git
  directory: subprojects/libcstdaux-1
- kind: git_repo
  url: github:c-util/c-utf8.git
  directory: subprojects/libcutf8-1
