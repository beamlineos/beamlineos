# SPDX-License-Identifier: MIT

kind: script
description: |
  The boot chain the installer puts on the target's ESP (docs/decisions.md D113), in
  /usr/lib/beamline/esp beside installer/config.bst's loader.conf:
    EFI/Beamline/shim<arch>.efi, grub<arch>.efi (systemd-boot), mm<arch>.efi, BOOT<ARCH>.CSV
    EFI/BOOT/BOOT<ARCH>.EFI (shim), fb<arch>.efi, mm<arch>.efi
    beamline.der
  Firmware without a boot entry starts shim from EFI/BOOT, which runs the fallback; the fallback
  creates the "Beamline" entry from the CSV and boots it. shim then starts systemd-boot, once
  beamline.der is a MOK; otherwise it starts MokManager, which can enroll beamline.der again.

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
- junctions/freedesktop-sdk.bst:components/python3.bst
- boot/shim.bst
- boot/systemd-boot-signed.bst

variables:
  secure-boot: '%{datadir}/%{os-id}/secure-boot'
  esp: '%{install-root}%{indep-libdir}/%{os-id}/esp'

config:
  commands:
  - |
    arch="%{efi-arch}"
    ARCH="$(echo "${arch}" | tr '[:lower:]' '[:upper:]')"
    install -d "%{esp}/EFI/Beamline" "%{esp}/EFI/BOOT"
    install -m644 "%{secure-boot}/shim/shim${arch}.efi" "%{esp}/EFI/Beamline/shim${arch}.efi"
    install -m644 "%{secure-boot}/systemd-boot${arch}.efi" "%{esp}/EFI/Beamline/grub${arch}.efi"
    install -m644 "%{secure-boot}/shim/mm${arch}.efi" "%{esp}/EFI/Beamline/mm${arch}.efi"
    install -m644 "%{secure-boot}/shim/shim${arch}.efi" "%{esp}/EFI/BOOT/BOOT${ARCH}.EFI"
    install -m644 "%{secure-boot}/shim/fb${arch}.efi" "%{esp}/EFI/BOOT/fb${arch}.efi"
    install -m644 "%{secure-boot}/shim/mm${arch}.efi" "%{esp}/EFI/BOOT/mm${arch}.efi"
    install -m644 "%{secure-boot}/beamline.der" "%{esp}/beamline.der"
    # The fallback reads UCS-2 with a byte order mark: loader,label,options,description.
    python3 - "%{esp}/EFI/Beamline/BOOT${ARCH}.CSV" "${arch}" <<'PY'
    import sys
    path, arch = sys.argv[1:]
    line = f"\ufeffshim{arch}.efi,Beamline,,This is the boot entry for Beamline\n"
    open(path, "wb").write(line.encode("utf-16-le"))
    PY
    chmod 0644 "%{esp}/EFI/Beamline/BOOT${ARCH}.CSV"
