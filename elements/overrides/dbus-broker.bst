# SPDX-FileCopyrightText: Freedesktop-SDK Developers
# SPDX-License-Identifier: MIT
#
# Override of FDSDK components/dbus-broker.bst: dbus-broker with its SELinux and audit
# support, so the bus asks the policy (docs/security.md §19.2, docs/decisions.md D30).
#
# Copied from: freedesktop-sdk c67967f99ce9aafd75bf5b3091f5d2da094bdd61
#   elements/components/dbus-broker.bst
# Changes from the original: source refs live in project.refs (ref-storage), dependencies
# carry the junction prefix, libselinux and audit are dependencies, -Dselinux=true
# -Daudit=true, and project_licensedir keeps FDSDK's path.

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
  # Keep FDSDK's license directory, as in overrides/systemd-base.bst.
  project_licensedir: '%{licensedir}/freedesktop-sdk'
  meson-local: >-
    -Dselinux=true
    -Daudit=true

# Meson wraps are not fetched by BuildStream. Replace as this issue is
# addressed: https://github.com/apache/buildstream-plugins/issues/5
# In the meantime, we have to keep it in sync by hand with the components
# provided by upstream https://github.com/bus1/dbus-broker/tree/v37/subprojects
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
