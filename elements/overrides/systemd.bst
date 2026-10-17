# SPDX-FileCopyrightText: Freedesktop-SDK Developers
# SPDX-License-Identifier: MIT












kind: filter
description: |
  systemd service manager.

  Use systemd-libs.bst if you only need the systemd libraries.

  This element requires some utility programs at runtime, including: `agetty`,
  `fsck` and `mkswap`. Multiple implementations of these are available and
  system integrators must choose one and include it in their system. FDSDK
  provides the util-linux implementations in `components/util-linux-full.bst`.

build-depends:
- overrides/systemd-base.bst

runtime-depends:
- junctions/freedesktop-sdk.bst:bootstrap/libxcrypt.bst
- junctions/freedesktop-sdk.bst:bootstrap/xz.bst
- junctions/freedesktop-sdk.bst:components/systemd-libs.bst
- junctions/freedesktop-sdk.bst:components/audit.bst
- junctions/freedesktop-sdk.bst:bootstrap/libselinux.bst
- junctions/freedesktop-sdk.bst:components/libgpg-error.bst
- junctions/freedesktop-sdk.bst:components/linux-pam.bst
- junctions/freedesktop-sdk.bst:components/kmod.bst
- junctions/freedesktop-sdk.bst:components/systemd-manifest.bst
- junctions/freedesktop-sdk.bst:components/tzdata.bst
- junctions/freedesktop-sdk.bst:components/shadow.bst
- junctions/freedesktop-sdk.bst:components/util-linux-libfdisk.bst
- junctions/freedesktop-sdk.bst:components/util-linux-libs.bst

- junctions/freedesktop-sdk.bst:components/util-linux-full.bst
- junctions/freedesktop-sdk.bst:components/libidn2.bst
- junctions/freedesktop-sdk.bst:components/libseccomp.bst
- junctions/freedesktop-sdk.bst:components/kbd.bst
- junctions/freedesktop-sdk.bst:components/cryptsetup.bst
- junctions/freedesktop-sdk.bst:components/p11-kit.bst
- junctions/freedesktop-sdk.bst:components/openssl.bst
- junctions/freedesktop-sdk.bst:components/curl.bst
- junctions/freedesktop-sdk.bst:components/libbpf.bst

(?):
- arch != "ppc64le":
    runtime-depends:
      (>):
      - junctions/freedesktop-sdk.bst:components/systemd-hwdb-maybe.bst

variables:
  
  project_licensedir: '%{licensedir}/freedesktop-sdk'

config:
  exclude:
  - systemd-libs
  - ukify
  - kernel-install

  include-orphans: True

public:
  bst:
    split-rules:
      runtime:
        (>):
        - '%{bindir}/resolvectl'
        - '%{bindir}/updatectl'
        - '%{indep-libdir}/environment.d/**'
        - '%{indep-libdir}/kernel/**'
        - '%{indep-libdir}/modprobe.d/**'
        - '%{indep-libdir}/sysctl.d/**'
        - '%{indep-libdir}/systemd/**'
        - '%{indep-libdir}/sysusers.d/**'
        - '%{indep-libdir}/tmpfiles.d/**'
        - '%{indep-libdir}/udev/**'
        - '%{datadir}/bash-completion/**'
        - '%{datadir}/dbus-1/**'
        - '%{datadir}/factory/**'
        - '%{datadir}/polkit-1/**'
        - '%{datadir}/systemd/**'
        - '%{datadir}/zsh/**'
        - '%{sysconfdir}/**'
        - '%{localstatedir}/**'
      devel:
        (>):
        - '%{indep-libdir}/udev/hwdb.d/**'
    overlap-whitelist:
    - "%{project_licensedir}/systemd"
    - "%{project_licensedir}/systemd/**"
