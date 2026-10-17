# SPDX-License-Identifier: MIT

kind: script
description: |
  systemd-native initrd (docs/spec.md §13, §36), built the way mkosi-initrd does it: a
  trimmed copy of the Virt root plus /etc/initrd-release, packed as a zstd cpio. systemd
  runs initrd.target, mounts root= and switches root; no dracut hooks or shell scripts.
  The Virt kernel has its boot path built in, so no kernel modules are included. The tree is
  trimmed in %{image-scratch}, outside the FUSE-staged sandbox root (docs/decisions.md D57).

(@):
- include/image/permissions.yml
- include/image/scratch.yml

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
- junctions/freedesktop-sdk.bst:components/cpio.bst
- junctions/freedesktop-sdk.bst:components/findutils.bst
- junctions/freedesktop-sdk.bst:components/systemd.bst
- junctions/freedesktop-sdk.bst:components/zstd.bst
- image/permissions.bst
- image/image-tools.bst
- junctions/freedesktop-sdk.bst:components/python3.bst
- filename: image/root-virt.bst
  config:
    location: /sysroot

config:
  commands:
  - |
    tree="%{image-scratch}/initrd"
    mkdir -p "%{image-scratch}"
    cp -a /sysroot "${tree}"

    
    rm -rf "${tree}"/usr/lib/modules/*/kernel \
           "${tree}"/usr/lib/modules/*/vmlinuz \
           "${tree}"/usr/share/locale \
           "${tree}"/usr/share/i18n \
           "${tree}"/usr/share/doc \
           "${tree}"/usr/share/man \
           "${tree}"/usr/share/info \
           "${tree}"/usr/share/licenses

    
    rm -f "${tree}/usr/bin/dash" "${tree}/usr/bin/sh" \
      "${tree}/usr/libexec/beamline-shell" "${tree}/etc/shells"

    
    rm -rf "${tree}/usr/bin/beamlinectl" "${tree}/usr/libexec/beamlinectld" \
      "${tree}/usr/share/varlink/org.beamline.Extensions.varlink" \
      "${tree}/usr/lib/beamline/extensions.d" \
      "${tree}/usr/lib/systemd/system/beamlinectld.socket" \
      "${tree}/usr/lib/systemd/system/beamlinectld@.service"
    rm -rf "${tree}/usr/lib/systemd/system/beamline-extension@.service" \
      "${tree}/usr/lib/systemd/system/beamline-extension@"*.service.d \
      "${tree}/usr/lib/systemd/system/beamline-extension-unlink@.service" \
      "${tree}/usr/lib/systemd/system/beamline-extension-unlink@"*.service.d \
      "${tree}/usr/lib/systemd/system/beamline-extensions-refresh.service" \
      "${tree}/usr/lib/systemd/system/beamline-extensions-start.service" \
      "${tree}/usr/lib/systemd/system/beamline-extension-state.service" \
      "${tree}/usr/lib/systemd/system/beamline-printing-start.service" \
      "${tree}/usr/lib/tmpfiles.d/30-beamlinectl-runtime.conf" \
      "${tree}/usr/share/polkit-1/actions/org.beamline.extensions.policy"

    
    
    
    rm -rf "${tree}/etc/systemd/system"

    
    
    
    install -d "${tree}/usr/lib/systemd/system/initrd.target.wants"
    ln -s ../systemd-confext-sysroot.service \
      "${tree}/usr/lib/systemd/system/initrd.target.wants/systemd-confext-sysroot.service"

    
    
    rm -rf "${tree}/etc/fstab" "${tree}/usr/lib/repart.d"

    
    
    rm -rf "${tree}/etc/selinux"

    
    
    %{apply-permissions}
    apply_permissions "${tree}"

    
    rm -f "${tree}/etc/initrd-release"
    cp "${tree}/usr/lib/os-release" "${tree}/etc/initrd-release"
    ln -sf usr/lib/systemd/systemd "${tree}/init"
    python3 "%{libexecdir}/%{os-id}-image-tools/check-policy.py" --artifact "${tree}"

  - |
    cd "%{image-scratch}/initrd"
    
    
    find . -newermt "@%{source-date-epoch}" -exec touch -h -d "@%{source-date-epoch}" {} +
    find . -mindepth 1 | LC_ALL=C sort \
      | cpio --quiet --reproducible -o -H newc \
      | zstd -q -19 -T0 > "%{install-root}/initrd"
    test -s "%{install-root}/initrd"
    du -h "%{install-root}/initrd"
