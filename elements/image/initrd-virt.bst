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

    # Not needed to find and mount the root filesystem.
    rm -rf "${tree}"/usr/lib/modules/*/kernel \
           "${tree}"/usr/lib/modules/*/vmlinuz \
           "${tree}"/usr/share/locale \
           "${tree}"/usr/share/i18n \
           "${tree}"/usr/share/doc \
           "${tree}"/usr/share/man \
           "${tree}"/usr/share/info \
           "${tree}"/usr/share/licenses

    # No shell is needed before switch-root (docs/spec.md §6, D62).
    rm -f "${tree}/usr/bin/dash" "${tree}/usr/bin/sh" \
      "${tree}/usr/libexec/beamline-shell" "${tree}/etc/shells"

    # Extension control belongs to the host, after DATA and the policy are available.
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

    # The host's enablement symlinks (networkd, resolved, ...) are not for the initrd;
    # initrd.target pulls in what the initrd needs. Unit start-rate counters survive
    # switch-root, so services failing here would also be refused in the host.
    rm -rf "${tree}/etc/systemd/system"

    # /etc's mutable layer on DATA is reduced to the allowlist and merged into /sysroot/etc
    # before switch-root, so PID 1 reads the final /etc (docs/decisions.md D56). The units are
    # inert in the host.
    install -d "${tree}/usr/lib/systemd/system/initrd.target.wants"
    ln -s ../systemd-confext-sysroot.service \
      "${tree}/usr/lib/systemd/system/initrd.target.wants/systemd-confext-sysroot.service"

    # DATA, its bind mounts and its growth belong to the host, after switch-root
    # (docs/spec.md §15); the initrd only mounts root= at /sysroot.
    rm -rf "${tree}/etc/fstab" "${tree}/usr/lib/repart.d"

    # cpio carries no labels, so the policy stays out of the initrd; systemd loads it in
    # the host after switch-root (docs/security.md §19.1).
    rm -rf "${tree}/etc/selinux"

    # The user database comes complete from the root (image/root-virt.bst runs sysusers);
    # its file modes do not survive the artifact (docs/decisions.md D31).
    %{apply-permissions}
    apply_permissions "${tree}"

    # systemd recognises an initrd by /etc/initrd-release and starts from /init.
    rm -f "${tree}/etc/initrd-release"
    cp "${tree}/usr/lib/os-release" "${tree}/etc/initrd-release"
    ln -sf usr/lib/systemd/systemd "${tree}/init"
    python3 "%{libexecdir}/%{os-id}-image-tools/check-policy.py" --artifact "${tree}"

  - |
    cd "%{image-scratch}/initrd"
    # The trimming above gave the directories it changed the build's time. Clamp every
    # timestamp to the source date, so the initrd (and with it the UKIs) is reproducible.
    find . -newermt "@%{source-date-epoch}" -exec touch -h -d "@%{source-date-epoch}" {} +
    find . -mindepth 1 | LC_ALL=C sort \
      | cpio --quiet --reproducible -o -H newc \
      | zstd -q -19 -T0 > "%{install-root}/initrd"
    test -s "%{install-root}/initrd"
    du -h "%{install-root}/initrd"
