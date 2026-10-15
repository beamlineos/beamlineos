# SPDX-License-Identifier: MIT

kind: script
description: |
  Finalised Virt root: integration toolbox removed, root-identity policy applied, system
  users created, presets applied, an uninitialized machine-id and an empty /var. Tools run
  from the build sandbox; the OS tree is only data at /sysroot.

(@):
- include/image/scratch.yml

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
- junctions/freedesktop-sdk.bst:components/findutils.bst
- junctions/freedesktop-sdk.bst:components/systemd.bst
- filename: image/root-virt-tree.bst
  config:
    location: /sysroot
# Reference trees used to compute exactly which files the toolbox added.
- filename: image/integration-tools.bst
  config:
    location: /reference/tools
- filename: profiles/virt.bst
  config:
    location: /reference/os
# System users of the official extensions, created here because /etc is read-only.
- filename: extensions/desktop-gnome-sysusers.bst
  config:
    location: /extension-sysusers
- filename: extensions/printing-scanning-sysusers.bst
  config:
    location: /extension-sysusers
# The official extensions' content, read only for the dynamic linker cache: glibc reads one
# /etc/ld.so.cache, so the base's covers every extension (docs/decisions.md D82).
- filename: desktop/gnome.bst
  config:
    location: /extension-content/desktop-gnome
- filename: posix/posix.bst
  config:
    location: /extension-content/posix
- filename: posix-devel/posix-devel.bst
  config:
    location: /extension-content/posix-devel
- filename: printing-scanning/printing-scanning.bst
  config:
    location: /extension-content/printing-scanning
# The public update keyring systemd-pull verifies channel signatures against.
- security/keys-update.bst
- image/base-user-tools-policy.bst
# The pruning tool and its lists (D88).
- image/image-tools.bst
- junctions/freedesktop-sdk.bst:components/python3.bst

config:
  commands:
  - |
    mkdir -p /work
    (cd /reference/tools && find . -mindepth 1 ! -type d | sort) > /work/tools-files
    (cd /reference/os && find . -mindepth 1 ! -type d | sort) > /work/os-files
    (cd /reference/tools && find . -mindepth 1 -type d | sort) > /work/tools-dirs
    (cd /reference/os && find . -mindepth 1 -type d | sort) > /work/os-dirs
    comm -23 /work/tools-files /work/os-files > /work/remove-files
    comm -23 /work/tools-dirs /work/os-dirs | sort -r > /work/remove-dirs
    while IFS= read -r path; do rm -f "/sysroot/${path#./}"; done < /work/remove-files
    while IFS= read -r path; do rmdir "/sysroot/${path#./}" 2>/dev/null || true; done < /work/remove-dirs
    echo "Removed $(wc -l < /work/remove-files) integration toolbox files"

  - |
    # docs/spec.md §18.1: su is absent. util-linux ships it and systemd depends on
    # util-linux, so it is removed here rather than by forking FDSDK's recipe.
    rm -f /sysroot/usr/bin/su /sysroot/etc/pam.d/su /sysroot/etc/pam.d/su-l
    # pkexec (polkit's setuid command runner) is absent too: run0 is the only escalation
    # (docs/spec.md §19, docs/decisions.md D55).
    rm -f /sysroot/usr/bin/pkexec
    # systemd's `run0 --empower` puts the caller in an "empower" group, and its polkit rule
    # grants that group every action without asking, against security §9.1's per-action
    # authorization. The rule leaves here, the group below (docs/decisions.md D76, step 1).
    rm -f /sysroot%{datadir}/polkit-1/rules.d/empower.rules
    # Accounts come from sysusers and homed; privilege comes from services (§22, D68).
    for command in newgrp passwd chsh chfn gpasswd chage newuidmap newgidmap \
      useradd usermod userdel groupadd groupmod groupdel chpasswd \
      pwconv pwunconv grpconv grpunconv vipw vigr; do
      rm -f "/sysroot/usr/bin/${command}" "/sysroot/usr/sbin/${command}"
    done
    # These upstream developer/maintenance scripts require interpreters the base
    # does not expose (docs/spec.md §5.2, §6, D61). Their original artifacts remain
    # available to extensions; none is used by a base service.
    rm -f /sysroot/usr/bin/ldd /sysroot/usr/bin/sotruss /sysroot/usr/bin/tzselect \
      /sysroot/usr/bin/xtrace /sysroot/usr/bin/psl-make-dafsa \
      /sysroot/usr/bin/e2scrub /sysroot/usr/bin/e2scrub_all \
      /sysroot/etc/pki/tls/misc/CA.pl /sysroot/etc/pki/tls/misc/tsget.pl
    rm -f /sysroot/usr/lib/systemd/system/e2scrub*.service \
      /sysroot/usr/lib/systemd/system/e2scrub*.timer
    # Updates verify against Beamline's keyring only (docs/decisions.md D52). systemd-pull
    # reads its vendor keyring, plus /etc/systemd/import-pubring.pgp when present; the vendor
    # keyring systemd ships (other distributions' keys) is replaced.
    install -Dm644 "%{datadir}/%{os-id}/keys/update/import-pubring.pgp" \
      /sysroot%{indep-libdir}/systemd/import-pubring.pgp

  - |
    # User-facing commands from library packages belong in posix (D63). The original
    # package artifacts remain intact; the posix delta retains these files.
    while read -r path rest; do
      case "$path" in ''|'#'*) continue ;; esac
      rm -f "/sysroot${path}"
    done < /usr/share/beamline/policy/base-user-tools.txt

  - |
    # Installation components leave SYSTEM; the installer extension, which only the installer
    # medium carries, ships them (docs/decisions.md D113).
    while read -r path rest; do
      case "$path" in ''|'#'*) continue ;; esac
      rm -f "/sysroot${path}"
    done < "%{libexecdir}/%{os-id}-image-tools/base-installer.txt"

  - |
    # systemd's virtualization and image services (portabled, machined, importd, nspawn,
    # vmspawn, mountfsd, nsresourced) leave the base; a later virtualization sysext ships them
    # (docs/decisions.md D87). Directories they leave empty go too.
    while read -r path rest; do
      case "$path" in ''|'#'*) continue ;; esac
      rm -f "/sysroot${path}"
      dir="${path%/*}"
      while [ -n "${dir}" ] && rmdir "/sysroot${dir}" 2>/dev/null; do dir="${dir%/*}"; done
    done < /usr/share/beamline/policy/base-virtualization.txt

  - |
    # GCC's sanitizer, transactional-memory and Fortran runtimes, device-mapper's headers,
    # a stray Python module and D-Bus' test tool: no base program uses them, and posix-devel alone
    # ships them (docs/decisions.md D88).
    # The SSH server's leftovers (D89) leave too.
    python3 "%{libexecdir}/%{os-id}-image-tools/prune-tree.py" --tree /sysroot \
      "%{libexecdir}/%{os-id}-image-tools/prune/base.txt" \
      "%{libexecdir}/%{os-id}-image-tools/prune/base-devel.txt"

  - |
    # /etc is read-only on the running system (docs/spec.md §14, docs/decisions.md D27), so
    # system users are created now: the base's and those of the official extensions
    # (§18.2, D38). The extensions' sysusers.d files ship with the extensions, so they are
    # only borrowed here. sysusers writes mode 0000; the unprivileged build sandbox must
    # still read the files to copy them.
    borrowed="$(cd /extension-sysusers%{datadir}/%{os-id}/extension-sysusers && find . -name '*.conf' | sort)"
    for conf in ${borrowed}; do
      install -m644 "/extension-sysusers%{datadir}/%{os-id}/extension-sysusers/${conf}" \
        "/sysroot/usr/lib/sysusers.d/beamline-extension-$(basename "${conf}")"
    done
    # The empower group leaves (above): its line is dropped from every file sysusers reads.
    mkdir -p "%{image-scratch}"
    for conf in /sysroot%{indep-libdir}/sysusers.d/*.conf; do
      while IFS= read -r line; do
        case "${line}" in "g empower "*) ;; *) printf '%s\n' "${line}" ;; esac
      done < "${conf}" > "%{image-scratch}/sysusers.conf"
      install -m644 "%{image-scratch}/sysusers.conf" "${conf}"
    done
    # Every system account gets its pinned number, so DATA's owners survive every update
    # (docs/decisions.md D106); an account the table lacks fails the build. The pinned copies
    # serve this one run: the image ships sysusers.d as upstream wrote it, which the extensions
    # compare with the base, and sysusers never runs again on a booted system (/etc/.updated).
    cp -a /sysroot%{indep-libdir}/sysusers.d "%{image-scratch}/sysusers.d.orig"
    python3 "%{libexecdir}/%{os-id}-image-tools/pin-sysusers.py" apply \
      "%{libexecdir}/%{os-id}-image-tools/system-ids.txt" /sysroot%{indep-libdir}/sysusers.d
    systemd-sysusers --root=/sysroot
    python3 "%{libexecdir}/%{os-id}-image-tools/pin-sysusers.py" check \
      "%{libexecdir}/%{os-id}-image-tools/system-ids.txt" /sysroot
    rm -rf /sysroot%{indep-libdir}/sysusers.d
    cp -a "%{image-scratch}/sysusers.d.orig" /sysroot%{indep-libdir}/sysusers.d
    rm -f /sysroot/usr/lib/sysusers.d/beamline-extension-*.conf
    chmod 0400 /sysroot/etc/shadow /sysroot/etc/gshadow
    # Root is locked with a nologin shell (docs/spec.md §18.1, docs/decisions.md D55).
    while IFS=: read -r name _ uid _ _ _ shell; do
      [ "${name}" = root ] || continue
      [ "${uid}" = 0 ] && [ "${shell}" = /usr/bin/nologin ] || { echo "root: uid ${uid}, shell ${shell}" >&2; exit 1; }
    done < /sysroot/etc/passwd
    while IFS=: read -r name password _; do
      [ "${name}" = root ] || continue
      case "${password}" in '!'*) ;; *) echo "root is not locked" >&2; exit 1 ;; esac
    done < /sysroot/etc/shadow
    # No empower group, and no rule that would honour one (D76, step 1).
    while IFS=: read -r name _; do
      [ "${name}" != empower ] || { echo "the empower group exists" >&2; exit 1; }
    done < /sysroot/etc/group
    [ ! -e /sysroot%{datadir}/polkit-1/rules.d/empower.rules ] || { echo "empower.rules exists" >&2; exit 1; }

  - systemctl --root=/sysroot preset-all

  - |
    # "uninitialized" marks a first boot: PID 1 overmounts a transient ID, and
    # systemd-machine-id-commit saves it in /etc's mutable layer, which the initrd merges on
    # later boots, so they are not first boots (docs/decisions.md D56).
    rm -f /sysroot/etc/machine-id
    printf 'uninitialized\n' > /sysroot/etc/machine-id
    chmod 0444 /sysroot/etc/machine-id
    # /etc is up to date with /usr by construction. Once the mutable layer makes /etc
    # writable, a missing /etc/.updated would start ldconfig, sysusers and hwdb-update
    # (ConditionNeedsUpdate=/etc), which would write into it (docs/decisions.md D56). Every
    # staged file carries the same timestamp, so the condition stays false.
    printf 'TIMESTAMP_NSEC=%s000000000\n' "%{source-date-epoch}" > /sysroot/etc/.updated

  - |
    # /var is state: tmpfiles and the services populate it at boot (§14). /data is the
    # mount point of DATA; /var and /home are bind mounts from it (§15).
    find /sysroot/var -mindepth 1 -delete
    mkdir -p /sysroot/data
    # Mount points for the boot partitions: systemd's gpt-auto generator mounts the ESP at
    # /efi and XBOOTLDR at /boot (docs/spec.md §15).
    mkdir -p /sysroot/efi /sysroot/boot

  - |
    # The root is read-only at runtime, so what boot-time services would write into it
    # is created now: the dynamic linker cache (ldconfig.service runs whenever it is
    # missing), and what tmpfiles creates outside the state and API filesystems
    # (/etc/mtab, factory copies into /etc, ...).
    #
    # The cache covers the base and every official extension (docs/decisions.md D82). glibc
    # reads only /etc/ld.so.cache, and overlayfs would show a single confext's copy, so the
    # extensions ship none. An entry for an extension that is not merged names a missing file;
    # glibc then searches the default directories, as it would without the entry. ldconfig -r
    # cannot follow symlinks out of its root, so the libraries are copied into one scratch root:
    # the base's first, then each extension's, from the directories the configuration names.
    union="%{image-scratch}/linker-cache"
    mkdir -p "${union}/etc/ld.so.conf.d"
    for tree in /sysroot /extension-content/*; do
      for conf in "${tree}"/etc/ld.so.conf.d/*.conf; do
        if [ -e "${conf}" ]; then
          cp --update=none "${conf}" "${union}/etc/ld.so.conf.d/"
        fi
      done
    done
    # ldconfig -r refuses the relative "include ld.so.conf.d/*.conf" of /etc/ld.so.conf.
    echo 'include /etc/ld.so.conf.d/*.conf' > "${union}/etc/ld.so.conf"
    dirs=""
    for conf in "${union}"/etc/ld.so.conf.d/*.conf; do
      [ -e "${conf}" ] || continue
      while read -r dir rest; do
        case "${dir}" in /*) dirs="${dirs} ${dir}" ;; esac
      done < "${conf}"
    done
    for tree in /sysroot /extension-content/*; do
      for dir in %{indep-libdir} %{libdir} ${dirs}; do
        [ -d "${tree}${dir}" ] || continue
        mkdir -p "${union}${dir}"
        find "${tree}${dir}" -maxdepth 1 \( -type f -o -type l \) -name '*.so*' \
          -exec cp -a --update=none -t "${union}${dir}" {} +
      done
    done
    ldconfig -X -r "${union}" -f /etc/ld.so.conf
    install -m644 "${union}/etc/ld.so.cache" /sysroot/etc/ld.so.cache
    # Mesa lives outside the default directories (FDSDK's GL/default/lib): the desktop needs
    # the cache to find it whichever extensions are merged beside it.
    ldconfig -p -C /sysroot/etc/ld.so.cache > "%{image-scratch}/linker-cache.txt"
    mesa=no
    while IFS= read -r line; do
      case "${line}" in *GL/default/lib/libgallium-*) mesa=yes ;; esac
    done < "%{image-scratch}/linker-cache.txt"
    [ "${mesa}" = yes ] || { echo "the linker cache does not list Mesa's libgallium" >&2; exit 1; }
    head -1 "%{image-scratch}/linker-cache.txt"
    systemd-tmpfiles --root=/sysroot --create --boot \
      --exclude-prefix=/dev --exclude-prefix=/proc --exclude-prefix=/sys \
      --exclude-prefix=/run --exclude-prefix=/tmp --exclude-prefix=/var \
      --exclude-prefix=/home --exclude-prefix=/data

  - cp -a /sysroot/. "%{install-root}/"
