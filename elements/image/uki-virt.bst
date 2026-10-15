# SPDX-License-Identifier: MIT

kind: script
description: |
  The unified kernel images (kernel + initrd + command line + os-release + systemd-stub) for
  XBOOTLDR (docs/spec.md §13, §15, §20). systemd-boot comes signed from
  boot/systemd-boot-signed.bst, as shim's second stage (D113). Kernel compilation and UKI generation
  are separate stages (§13). Three UKIs share the kernel and initrd:
    xbootldr/EFI/Linux/beamline_<snapshot>.efi      production
    xbootldr/EFI/Linux/beamline-dev_<snapshot>.efi  development: SELinux permissive (§13)
    xbootldr/EFI/Linux/beamline-recovery.efi        the RecoveryOS stub (§20)
  and a fourth, for the installer medium only (image/install-virt.bst, docs/decisions.md D106):
    install/EFI/Linux/beamline-install_<snapshot>.efi  the installer's live system
  whose extra initrd hands the installer extension to the root (installer/initrd.bst, D113).
  Every image is signed with the development Secure Boot key (docs/security.md §19.4), and
  the signatures are verified here. SYSTEM's verity root hash is signed with the development
  verity key; the signature rides in the signed UKI as a second initrd, and the kernel checks it
  against its built-in keyring when the initrd activates SYSTEM (docs/decisions.md D101).

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
- junctions/freedesktop-sdk.bst:components/systemd.bst
- junctions/freedesktop-sdk.bst:components/systemd-ukify.bst
- junctions/freedesktop-sdk.bst:components/sbsigntools-maybe.bst
- junctions/freedesktop-sdk.bst:components/cpio.bst
- junctions/freedesktop-sdk.bst:components/findutils.bst
- junctions/freedesktop-sdk.bst:components/openssl.bst
- security/keys-uki.bst
- security/keys-verity.bst
- filename: kernel/linux-virt.bst
  config:
    location: /kernel
- filename: image/initrd-virt.bst
  config:
    location: /initrd
- filename: base/os-release.bst
  config:
    location: /os-release
- filename: image/system-virt.bst
  config:
    location: /system
- filename: installer/initrd.bst
  config:
    location: /installer-initrd

variables:
  uki-keys: '%{datadir}/%{os-id}/keys/uki'
  verity-keys: '%{datadir}/%{os-id}/keys/verity'
  # Where the initrd finds SYSTEM's root hash signature (D101)
  roothash-sig: /usr/lib/%{os-id}/system.roothash.p7s
  uki-dir: '%{install-root}/xbootldr/EFI/Linux'
  # SYSTEM, read-only EROFS under dm-verity (docs/spec.md §13, §14): the commands prepend
  # roothash=, from which the initrd derives the data and hash partitions' UUIDs and sets up
  # /dev/mapper/root (docs/decisions.md D47). The first boot asks only for the first account
  # (beamline-first-user.service, D112): root stays locked (§18.1), and settings come from the
  # image or from credentials (systemd-firstboot asks nothing, by its drop-in).
  # Extension images' signatures are checked by the kernel only; systemd's userspace
  # fallback is off (docs/decisions.md D53).
  kernel-cmdline: >-
    rootfstype=erofs ro
    console=%{serial-console}
    systemd.show_status=yes
    systemd.allow_userspace_verity=0
    systemd.verity_root_options=root-hash-signature=%{roothash-sig}
  # The development UKI differs only by its command line: SELinux permissive (§13,
  # docs/security.md §19.4).
  kernel-cmdline-dev: enforcing=0
  # The RecoveryOS stub boots the same kernel and initrd into beamline-recovery-stub.target,
  # which reports itself and powers off (docs/decisions.md D48). It mounts nothing: without
  # roothash=, the gpt-auto generator would otherwise try to activate a SYSTEM slot.
  # The installer on the medium (0.0.4.3 step 2, docs/decisions.md D106): the production command
  # line, booted as a live system. Its extra initrd copies the installer extension from beside the
  # UKI into /run/extensions (D113). PID 1 starts basic.target; the root's systemd-sysext merges the
  # extension, and the extension's drop-in for the restart after the merge (D41) starts the
  # installer's target, which comes with it, instead of the default target. DATA is a tmpfs, so the
  # medium is never written; systemd-repart never runs, so the medium is never repartitioned.
  # /etc is SYSTEM's own, read-only: no confext merges, and its mutable layer would sit on the
  # tmpfs, whose files created before the policy loads are labelled tmpfs_t (journald, udev and the
  # bus then cannot read /etc). Nothing grows /data, and the journal stays in /run. It never enters
  # the update channel.
  kernel-cmdline-install: >-
    rd.systemd.mount-extra=tmpfs:/sysroot/data:tmpfs:mode=0755
    rd.systemd.mask=systemd-repart.service
    systemd.mask=systemd-repart.service
    rd.systemd.mask=beamline-etc-allowlist.service
    rd.systemd.mask=systemd-confext-sysroot.service
    systemd.mask=systemd-confext.service
    systemd.mask=systemd-growfs@data.service
    systemd.mask=systemd-journal-flush.service
    rd.systemd.wants=beamline-installer-extension.service
    systemd.unit=basic.target
  kernel-cmdline-recovery: >-
    rd.systemd.unit=beamline-recovery-stub.target
    rd.systemd.gpt_auto=0
    console=%{serial-console}
    systemd.show_status=yes

config:
  commands:
  - |
    install -d /work "%{uki-dir}"
    python3 - /os-release%{indep-libdir}/os-release /work <<'EOF'
    import sys
    base = open(sys.argv[1]).read()
    def variant(name, pretty, image_id):
        lines = [l for l in base.splitlines() if not l.startswith(("PRETTY_NAME=", "IMAGE_ID="))]
        lines += [f'PRETTY_NAME="{pretty}"', f"IMAGE_ID={image_id}"]
        open(f"{sys.argv[2]}/{name}", "w").write("\n".join(lines) + "\n")
    fields = dict(l.split("=", 1) for l in base.splitlines() if "=" in l)
    pretty = fields["PRETTY_NAME"].strip('"')
    variant("os-release", pretty, "%{os-id}")
    variant("os-release-dev", pretty + ", SELinux permissive", "%{os-id}-dev")
    variant("os-release-recovery", fields["NAME"].strip('"') + " RecoveryOS (stub)", "%{os-id}-recovery")
    variant("os-release-install", "Install " + pretty, "%{os-id}-install")
    EOF

  - |
    kver="$(ls /kernel/usr/lib/modules)"
    roothash="$(python3 -c 'import json, sys
    print(next(p["roothash"] for p in json.load(open(sys.argv[1])) if p.get("roothash") not in (None, "", "-")))' /system/system.json)"
    # SYSTEM's root hash, signed (PKCS#7 without attributes, so the signature is reproducible),
    # packed as a second initrd that the kernel unpacks over the first (D101).
    install -d "/work/roothash-sig$(dirname "%{roothash-sig}")"
    printf '%s' "${roothash}" > /work/roothash.txt
    openssl smime -sign -nocerts -noattr -binary -in /work/roothash.txt \
      -inkey "%{verity-keys}/verity.key" -signer "%{verity-keys}/verity.crt" \
      -outform der -out "/work/roothash-sig%{roothash-sig}"
    openssl smime -verify -binary -inform der -in "/work/roothash-sig%{roothash-sig}" \
      -content /work/roothash.txt -certfile "%{verity-keys}/verity.crt" \
      -CAfile "%{verity-keys}/verity.crt" -purpose any > /dev/null
    ( cd /work/roothash-sig
      sig="${PWD}%{roothash-sig}"
      set -- . usr usr/lib "usr/lib/%{os-id}" "usr/lib/%{os-id}/$(basename "${sig}")"
      touch -h -d "@%{source-date-epoch}" "$@"
      printf '%s\n' "$@" | cpio --quiet --reproducible -o -H newc ) > /work/roothash-sig.cpio
    # The installer UKI's extra initrd (D113).
    ( cd /installer-initrd%{datadir}/%{os-id}/installer-initrd
      find . | sort > /work/installer-initrd.list
      xargs touch -h -d "@%{source-date-epoch}" < /work/installer-initrd.list
      cpio --quiet --reproducible -o -H newc < /work/installer-initrd.list ) > /work/installer-initrd.cpio
    uki() {
      output="$1"; osrelease="$2"; cmdline="$3"; shift 3
      ukify build \
        --linux "/kernel/usr/lib/modules/${kver}/vmlinuz" \
        --initrd /initrd/initrd "$@" \
        --os-release "@${osrelease}" \
        --uname "${kver}" \
        --cmdline "${cmdline}" \
        --stub "/usr/lib/systemd/boot/efi/linux%{efi-arch}.efi.stub" \
        --signtool systemd-sbsign --sign-kernel \
        --secureboot-private-key "%{uki-keys}/db.key" \
        --secureboot-certificate "%{uki-keys}/db.crt" \
        --output "%{uki-dir}/${output}"
    }
    uki "%{os-id}_%{snapshot-id}.efi" /work/os-release \
      "roothash=${roothash} %{kernel-cmdline}" --initrd /work/roothash-sig.cpio
    uki "%{os-id}-dev_%{snapshot-id}.efi" /work/os-release-dev \
      "roothash=${roothash} %{kernel-cmdline} %{kernel-cmdline-dev}" --initrd /work/roothash-sig.cpio
    uki "%{os-id}-recovery.efi" /work/os-release-recovery "%{kernel-cmdline-recovery}"
    uki "%{os-id}-install_%{snapshot-id}.efi" /work/os-release-install \
      "roothash=${roothash} %{kernel-cmdline} %{kernel-cmdline-install}" --initrd /work/roothash-sig.cpio \
      --initrd /work/installer-initrd.cpio
    install -d "%{install-root}/install/EFI/Linux"
    mv "%{uki-dir}/%{os-id}-install_%{snapshot-id}.efi" "%{install-root}/install/EFI/Linux/"

  - |
    chmod 0644 "%{uki-dir}"/*.efi "%{install-root}"/install/EFI/Linux/*.efi

  - |
    # systemd-sbsign cannot verify; sbsigntools can. Every image must carry a signature
    # that the development certificate validates.
    for efi in "%{uki-dir}"/*.efi "%{install-root}"/install/EFI/Linux/*.efi; do
      sbverify --cert "%{uki-keys}/db.crt" "${efi}"
    done
