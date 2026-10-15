# SPDX-License-Identifier: MIT

kind: script
description: |
  systemd-boot signed with the development db key, shim's second stage on every Beamline ESP
  (docs/decisions.md D113), and the certificate to enroll as a MOK:
    /usr/share/beamline/secure-boot/systemd-boot<arch>.efi
    /usr/share/beamline/secure-boot/beamline.der
  shim starts systemd-boot only once beamline.der is a MOK, and systemd-boot then has shim verify
  the UKIs. DEVELOPMENT ONLY: the key is public, so beamline.der must never be enrolled on real
  hardware; a private release key comes first (0.0.4.5).

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
- junctions/freedesktop-sdk.bst:components/systemd.bst
- junctions/freedesktop-sdk.bst:components/sbsigntools-maybe.bst
- junctions/freedesktop-sdk.bst:components/openssl.bst
- security/keys-uki.bst

variables:
  uki-keys: '%{datadir}/%{os-id}/keys/uki'
  out: '%{install-root}%{datadir}/%{os-id}/secure-boot'

config:
  commands:
  - |
    install -d "%{out}"
    /usr/lib/systemd/systemd-sbsign sign \
      --private-key "%{uki-keys}/db.key" --certificate "%{uki-keys}/db.crt" \
      --output "%{out}/systemd-boot%{efi-arch}.efi" \
      "%{indep-libdir}/systemd/boot/efi/systemd-boot%{efi-arch}.efi"
    sbverify --cert "%{uki-keys}/db.crt" "%{out}/systemd-boot%{efi-arch}.efi"
    openssl x509 -in "%{uki-keys}/db.crt" -outform DER -out "%{out}/beamline.der"
    chmod 0644 "%{out}"/*
