# SPDX-FileCopyrightText: Freedesktop-SDK Developers
# SPDX-License-Identifier: MIT










kind: meson
description: |
  PAM authentication system.

  This element provides PAM (Pluggable Authentication Modules), a framework
  used by most Linux operating systems to authenticate and manage user logins.
  This element includes the client library and the core modules.

  See `components/linux-pam.bst` for a base PAM configuration.

  This element is intended for system integration, it is not included
  in Flatpak or OCI images.

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/buildsystem-meson.bst
- junctions/freedesktop-sdk.bst:components/flex.bst

depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-minimal.bst
- junctions/freedesktop-sdk.bst:components/audit.bst
- junctions/freedesktop-sdk.bst:components/libeconf.bst
- junctions/freedesktop-sdk.bst:bootstrap/libselinux.bst

variables:
  
  project_licensedir: '%{licensedir}/freedesktop-sdk'

  meson-local: >-
    -Dpam_lastlog=enabled
    -Dexamples=false
    -Dlogind=disabled
    -Dnis=disabled
    -Dselinux=enabled
    -Ddocs=disabled
    -Delogind=disabled
    -Dpwaccess=disabled

config:
  install-commands:
    (>):
    - rm -rf "%{install-root}/var/run"

public:
  initial-script:
    script: |
      #!/bin/bash
      sysroot="${1}"
      file="${sysroot}%{bindir}/unix_chkpwd"
      if [ -f "$file" ]; then
          chmod 4755 "$file"
      fi
  bst:
    split-rules:
      devel:
        (>):
        - '%{libdir}/libpam.so'
        - '%{libdir}/libpam_misc.so'
        - '%{libdir}/libpamc.so'
      vm-only:
        
        
      - '%{sysconfdir}'
      - '%{sysconfdir}/**'
      - '%{bindir}'
      - '%{bindir}/**'
      - '%{datadir}'
      - '%{datadir}/**'
  cpe:
    product: linux-pam

sources:
- kind: git_repo
  url: github:linux-pam/linux-pam.git
  track: v*
