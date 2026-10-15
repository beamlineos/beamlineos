# SPDX-FileCopyrightText: Freedesktop-SDK Developers
# SPDX-License-Identifier: MIT
#
# Override of FDSDK components/systemd.bst: the systemd filter over
# overrides/systemd-base.bst, without the runtime dependencies of the features the base
# disables (docs/spec.md §5.2).
#
# Copied from: freedesktop-sdk c67967f99ce9aafd75bf5b3091f5d2da094bdd61
#   elements/components/systemd.bst
# Changes from the original: dependencies carry the junction prefix (the build dependency
# is the systemd-base override), target_arch conditions use arch, libapparmor and
# libmicrohttpd are dropped from runtime-depends, libselinux is added to them (SELinux is
# enabled, docs/security.md §19.2), and project_licensedir keeps FDSDK's path.

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
# systemd services exist that call `agetty`, `fsck`, `mkswap` from util-linux-full.
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
  # Keep FDSDK's license directory, as in overrides/systemd-base.bst.
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
