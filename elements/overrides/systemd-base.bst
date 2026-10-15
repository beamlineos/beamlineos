# SPDX-FileCopyrightText: Freedesktop-SDK Developers
# SPDX-License-Identifier: MIT
#
# Override of FDSDK components/_private/systemd-base.bst, tracking systemd `main`
# (docs/spec.md §2.2, §31). Every FDSDK systemd element (systemd, systemd-libs,
# systemd-ukify, systemd-kernel-install) is a filter over this one.
#
# Copied from: freedesktop-sdk c67967f99ce9aafd75bf5b3091f5d2da094bdd61
#   elements/components/_private/systemd-base.bst
# Changes from the original: dependencies carry the junction prefix, target_arch
# conditions use arch, the source is inline, tracks main and uses the classic git source
# (it was elements/include/systemd.yml, git_repo, track v*; decisions D33), the preset file
# is a local copy,
# project_licensedir keeps FDSDK's path (FDSDK's systemd filters whitelist overlaps there),
# features the base does not use are disabled with their build dependencies removed
# (docs/spec.md §5.2): AppArmor, QR codes, xkbcommon, journal-remote/upload (microhttpd),
# and SELinux is enabled with libselinux as a build dependency (docs/security.md §19.2).
# Three downstream patches apply, each explained beside it in files/patches: the transient-context
# bound (D70, D72), the unit file load check (D97) and sysinstall's `--boot-loader=no` (D113).

kind: meson

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-minimal.bst
- junctions/freedesktop-sdk.bst:public-stacks/buildsystem-meson.bst
- junctions/freedesktop-sdk.bst:bootstrap/sed.bst
- junctions/freedesktop-sdk.bst:bootstrap/gawk.bst
- junctions/freedesktop-sdk.bst:bootstrap/grep.bst
- junctions/freedesktop-sdk.bst:bootstrap/diffutils.bst
- junctions/freedesktop-sdk.bst:components/audit.bst
- junctions/freedesktop-sdk.bst:bootstrap/libselinux.bst
- junctions/freedesktop-sdk.bst:components/gperf.bst
- junctions/freedesktop-sdk.bst:components/m4.bst
- junctions/freedesktop-sdk.bst:components/libcap.bst
- junctions/freedesktop-sdk.bst:components/libgcrypt.bst
- junctions/freedesktop-sdk.bst:components/libgpg-error.bst
- junctions/freedesktop-sdk.bst:components/libseccomp.bst
- junctions/freedesktop-sdk.bst:components/lz4.bst
- junctions/freedesktop-sdk.bst:components/zstd.bst
- junctions/freedesktop-sdk.bst:components/util-linux-libfdisk.bst
- junctions/freedesktop-sdk.bst:components/util-linux-libs.bst
# systemd services exist that call `agetty`, `fsck`, `mkswap` from util-linux-full.
- junctions/freedesktop-sdk.bst:components/util-linux-full.bst
- junctions/freedesktop-sdk.bst:components/libarchive.bst
- junctions/freedesktop-sdk.bst:components/linux-pam.bst
- junctions/freedesktop-sdk.bst:components/kmod.bst
- junctions/freedesktop-sdk.bst:components/python3-pyelftools.bst
- junctions/freedesktop-sdk.bst:components/libxslt.bst
- junctions/freedesktop-sdk.bst:components/docbook-xsl.bst
- junctions/freedesktop-sdk.bst:components/_private/cryptsetup-lvm2-stage1.bst
- junctions/freedesktop-sdk.bst:components/p11-kit.bst
- junctions/freedesktop-sdk.bst:components/libfido2.bst
- junctions/freedesktop-sdk.bst:components/libidn2.bst
- junctions/freedesktop-sdk.bst:components/openssl.bst
- junctions/freedesktop-sdk.bst:components/python3-pefile.bst
- junctions/freedesktop-sdk.bst:components/python3-jinja2.bst
- junctions/freedesktop-sdk.bst:components/tpm2-tss.bst
- junctions/freedesktop-sdk.bst:components/curl.bst
- junctions/freedesktop-sdk.bst:components/iptables.bst
- junctions/freedesktop-sdk.bst:components/bpf-maybe.bst
- junctions/freedesktop-sdk.bst:components/libbpf.bst
- junctions/freedesktop-sdk.bst:components/llvm.bst

variables:
  # %{project-name} is "beamline" here; keep FDSDK's license directory so the overlap
  # whitelists of FDSDK's systemd filter elements still match.
  project_licensedir: '%{licensedir}/freedesktop-sdk'

  efi: 'false'
  bpf-framework: 'disabled'
  (?):
  - arch in ["x86_64", "i686", "aarch64", "riscv64", "loongarch64"]:
      efi: 'true'
  - arch in ["x86_64", "aarch64"]:
      bpf-framework: 'enabled'

  meson-local: >-
    -Dmode=release
    -Daudit=enabled
    -Dseccomp=enabled
    -Dsystem-uid-max=999
    -Dsystem-gid-max=999
    -Dusers-gid=100
    -Ddefault-user-shell=/usr/libexec/beamline-shell
    -Dopenssl=enabled
    -Dpam=enabled
    -Dbootloader=%{efi}
    -Defi=%{efi}
    -Dfirstboot=true
    -Dzlib=enabled
    -Dzstd=enabled
    -Dbzip2=enabled
    -Dxz=enabled
    -Dlz4=enabled
    -Ddefault-dnssec=no
    -Didn=true
    -Drepart=enabled
    -Dman=enabled
    -Dhtml=enabled
    -Dlibcryptsetup=enabled
    -Dlibcryptsetup-plugins=enabled
    -Dp11kit=enabled
    -Dlibfido2=enabled
    -Dapparmor=disabled
    -Dtpm=true
    -Dtpm2=enabled
    -Dsbat-distro=freedesktop-sdk
    -Dsbat-distro-generation=1
    -Dsbat-distro-summary="Freedesktop SDK"
    -Dsbat-distro-url=https://gitlab.com/freedesktop-sdk/freedesktop-sdk/
    -Dversion-tag="$(git describe --abbrev=7 | sed "s/^v//")"
    -Dqrencode=disabled
    -Dxkbcommon=disabled
    -Dlibidn2=enabled
    -Dxenctrl=disabled
    -Dbpf-framework=%{bpf-framework}
    -Dgnutls=disabled
    -Dglib=disabled
    -Ddbus=disabled
    -Dukify=%{efi}
    -Dkernel-install=true
    -Dvmlinux-h=provided
    -Dvmlinux-h-path='%{includedir}/%{gcc_triplet}/linux/vmlinux.h'
    -Dselinux=enabled
    -Dsysupdated=enabled
    -Dremote=disabled
    -Dmicrohttpd=disabled

config:
  install-commands:
    (>):
    - |
      shopt -s nullglob
      for name in %{install-root}%{indep-libdir}/systemd/boot/efi/*.elf.stub
      do
      chmod a-x ${name}
      done
      shopt -u nullglob

    - |
      install -Dm644 -t '%{install-root}%{indep-libdir}/systemd/system-preset' 90-sysupdate.preset

public:
  cpe:
    vendor: 'freedesktop'
    product: 'systemd'

  bst:
    split-rules:
      kernel-install:
      - '%{bindir}/kernel-install'
      - '%{datadir}/bash-completion/completions/kernel-install'
      - '%{datadir}/zsh/site-functions/_kernel-install'
      - '%{indep-libdir}/kernel'
      - '%{indep-libdir}/kernel/**'
      - '%{mandir}/man8/kernel-install.8'
      - '%{debugdir}%{bindir}/kernel-install.debug'
      ukify:
      - '%{bindir}/ukify'
      - '%{indep-libdir}/systemd/ukify'
      - '%{mandir}/man1/ukify.1'
      systemd-libs:
      - '%{libdir}'
      - '%{libdir}/libsystemd*.so*'
      - '%{libdir}/libudev*.so*'
      - '%{libdir}/libnss_resolve.so*'
      - '%{libdir}/pkgconfig'
      - '%{libdir}/pkgconfig/libsystemd.pc'
      - '%{libdir}/pkgconfig/libudev.pc'
      - '%{includedir}'
      - '%{includedir}/libudev.h'
      - '%{includedir}/systemd'
      - '%{includedir}/systemd/**'
      - '%{debugdir}/dwz/%{stripdir-suffix}/*'
      - '%{debugdir}%{libdir}/libsystemd*.so*'
      - '%{debugdir}%{libdir}/libudev*.so*'
      - '%{debugdir}%{libdir}/libnss_resolve.so*'
      - '%{sourcedir}'
      - '%{sourcedir}/**'
      systemd-license:
      - "%{project_licensedir}"
      - "%{project_licensedir}/**"

sources:
- kind: git
  url: github:systemd/systemd.git
  track: main
  ref-format: git-describe
  version-guess-pattern: '(\d+)(?:\.(\d+))?'
- kind: local
  path: files/overrides/systemd/90-sysupdate.preset
- kind: patch
  path: files/patches/systemd-transient-selinux-bound.patch
- kind: patch
  path: files/patches/systemd-unit-load-selinux.patch
- kind: patch
  path: files/patches/systemd-sysinstall-boot-loader.patch
