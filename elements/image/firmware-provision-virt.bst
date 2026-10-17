# SPDX-License-Identifier: MIT

kind: script
description: |
  Test only (docs/decisions.md D113): a small disk that provisions a test VM's UEFI variables the
  way a PC is sold. Booted once on Secure Boot capable firmware in setup mode, its systemd-boot
  enrolls loader/keys/auto and reboots:
    PK   the development certificate (the test platform's owner)
    KEK  the development certificate, Microsoft's KEK CA 2011 and KEK 2K CA 2023
    db   Microsoft's UEFI CA 2011 and UEFI CA 2023 only
  Nothing of Beamline's then starts without shim and a MOK. ci/test-install boots it first.
  Never published, never on a medium. Output: provision.raw.

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
- junctions/freedesktop-sdk.bst:components/systemd.bst
- junctions/freedesktop-sdk.bst:components/python3.bst
- junctions/freedesktop-sdk.bst:components/openssl.bst
- junctions/freedesktop-sdk.bst:components/dosfstools.bst
- junctions/freedesktop-sdk.bst:components/mtools.bst
- security/keys-uki.bst
- image/image-tools.bst
- boot/systemd-boot-signed.bst
- boot/microsoft-kek-ca-2011.bst
- boot/microsoft-kek-ca-2023.bst
- boot/microsoft-uefi-ca-2011.bst
- boot/microsoft-uefi-ca-2023.bst

variables:
  uki-keys: '%{datadir}/%{os-id}/keys/uki'
  secure-boot: '%{datadir}/%{os-id}/secure-boot'
  
  microsoft-owner: 77fa9abd-0359-4d32-bd60-28f4e78f784b
  provision-seed: 5f2e7c41-8a93-4d6b-b1e0-6c4d2a9f3e17

environment:
  SOURCE_DATE_EPOCH: '%{source-date-epoch}'
  SYSTEMD_REPART_MKFS_OPTIONS_VFAT: --invariant
  TMPDIR: /work/tmp

config:
  commands:
  - |
    esp=/work/esp
    ms="%{secure-boot}/upstream"
    ARCH="$(echo "%{efi-arch}" | tr '[:lower:]' '[:upper:]')"
    install -d "${esp}/EFI/BOOT" "${esp}/loader/keys/auto" /work/definitions /work/tmp
    install -m644 "%{secure-boot}/systemd-boot%{efi-arch}.efi" "${esp}/EFI/BOOT/BOOT${ARCH}.EFI"
    printf 'timeout 0\nsecure-boot-enroll force\nsecure-boot-enroll-timeout-sec hidden\n' \
      > "${esp}/loader/loader.conf"
    python3 "%{libexecdir}/%{os-id}-image-tools/make-enrollment.py" \
      --key "%{uki-keys}/db.key" --cert "%{uki-keys}/db.crt" --time "%{source-date-epoch}" \
      --kek "%{uki-keys}/db.crt" \
      --kek "${ms}/microsoft-kek-ca-2011.crt=%{microsoft-owner}" \
      --kek "${ms}/microsoft-kek-ca-2023.crt=%{microsoft-owner}" \
      --db "${ms}/microsoft-uefi-ca-2011.crt=%{microsoft-owner}" \
      --db "${ms}/microsoft-uefi-ca-2023.crt=%{microsoft-owner}" \
      "${esp}/loader/keys/auto"
    printf '[Partition]\nType=esp\nFormat=vfat\nCopyFiles=/esp:/\nSizeMinBytes=32M\nSizeMaxBytes=32M\n' \
      > /work/definitions/10-esp.conf
    systemd-repart --offline=yes --dry-run=no --empty=create --size=auto \
      --seed=%{provision-seed} --definitions=/work/definitions --copy-source=/work \
      "%{install-root}/provision.raw"
