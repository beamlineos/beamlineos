# SPDX-License-Identifier: MIT

kind: script
description: |
  The installer medium (0.0.4.3, docs/decisions.md D106, D113), built offline by systemd-repart:
    ESP       Debian's shim at the removable path, systemd-boot as its second stage (grub<arch>.efi),
              MokManager, and beamline.der. Firmware holding Microsoft's keys starts shim; shim
              starts MokManager until beamline.der is a MOK, then systemd-boot, which starts the
              installer UKI.
    XBOOTLDR  the installer UKI, with the installer extension beside it (.extra.d), and the UKIs
              the installer copies to the target (/beamline/uki)
    SYSTEM-A  with its verity hash tree
  No DATA and no other extension: the live system's DATA is a tmpfs, and installed systems fetch
  their extensions at first boot. Output: install.raw.

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
- junctions/freedesktop-sdk.bst:components/systemd.bst
- junctions/freedesktop-sdk.bst:components/python3.bst
- junctions/freedesktop-sdk.bst:components/dosfstools.bst
- junctions/freedesktop-sdk.bst:components/mtools.bst
- image/repart-install.bst
- boot/shim.bst
- boot/systemd-boot-signed.bst
- filename: extensions/installer.bst
  config:
    location: /installer-extension
- filename: image/system-virt.bst
  config:
    location: /system
- filename: image/uki-virt.bst
  config:
    location: /work/src

variables:
  
  
  medium-seed: 3c5e8a71-9d24-4b6f-8e13-5a7c0d9f2b64

environment:
  SOURCE_DATE_EPOCH: '%{source-date-epoch}'
  
  SYSTEMD_REPART_MKFS_OPTIONS_VFAT: --invariant
  TMPDIR: /work/tmp

config:
  commands:
  - |
    
    
    medium=/work/medium
    sb="%{datadir}/%{os-id}/secure-boot"
    arch="%{efi-arch}"
    ARCH="$(echo "${arch}" | tr '[:lower:]' '[:upper:]')"
    install -d "${medium}/esp/EFI/BOOT" "${medium}/esp/loader" \
      "${medium}/xbootldr/EFI/Linux" "${medium}/xbootldr/%{os-id}/uki"
    install -m644 "${sb}/shim/shim${arch}.efi" "${medium}/esp/EFI/BOOT/BOOT${ARCH}.EFI"
    install -m644 "${sb}/shim/mm${arch}.efi" "${medium}/esp/EFI/BOOT/mm${arch}.efi"
    install -m644 "${sb}/systemd-boot${arch}.efi" "${medium}/esp/EFI/BOOT/grub${arch}.efi"
    install -m644 "${sb}/beamline.der" "${medium}/esp/beamline.der"
    printf 'timeout 0\nconsole-mode keep\neditor no\ndefault %{os-id}-install_*\n' \
      > "${medium}/esp/loader/loader.conf"
    for uki in /work/src/install/EFI/Linux/*.efi; do
      install -m644 "${uki}" "${medium}/xbootldr/EFI/Linux/"
      
      install -D -m644 /installer-extension/installer.sysext.raw \
        "${medium}/xbootldr/EFI/Linux/$(basename "${uki}").extra.d/installer.sysext.raw"
    done
    install -m644 /work/src/xbootldr/EFI/Linux/*.efi "${medium}/xbootldr/%{os-id}/uki/"

  - |
    
    
    cp -r "%{datadir}/%{os-id}/repart/install" /work/definitions
    python3 - /system/system.json /work/definitions "%{os-id}_%{snapshot-id}" <<'EOF'
    import json, os, sys
    partitions = json.load(open(sys.argv[1]))
    def uuid(verity):
        found = [p["uuid"] for p in partitions
                 if p["type"].startswith("root-") and p["type"].endswith("-verity") == verity]
        assert len(found) == 1, (verity, partitions)
        return found[0]
    for name, verity in (("20-system-a.conf", False), ("21-system-a-verity.conf", True)):
        dropin = os.path.join(sys.argv[2], name + ".d")
        os.makedirs(dropin)
        with open(os.path.join(dropin, "uuid.conf"), "w") as f:
            f.write(f"[Partition]\nUUID={uuid(verity)}\nLabel={sys.argv[3]}\n")
    EOF

  - |
    mkdir -p "${TMPDIR}"
    systemd-repart \
      --offline=yes \
      --dry-run=no \
      --empty=create \
      --size=auto \
      --seed=%{medium-seed} \
      --definitions=/work/definitions \
      --copy-source=/work/medium \
      "%{install-root}/install.raw"
