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

- filename: image/integration-tools.bst
  config:
    location: /reference/tools
- filename: profiles/virt.bst
  config:
    location: /reference/os

- filename: extensions/desktop-gnome-sysusers.bst
  config:
    location: /extension-sysusers
- filename: extensions/printing-scanning-sysusers.bst
  config:
    location: /extension-sysusers


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

- security/keys-update.bst
- image/base-user-tools-policy.bst

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
    
    
    rm -f /sysroot/usr/bin/su /sysroot/etc/pam.d/su /sysroot/etc/pam.d/su-l
    
    
    rm -f /sysroot/usr/bin/pkexec
    
    
    
    rm -f /sysroot%{datadir}/polkit-1/rules.d/empower.rules
    
    for command in newgrp passwd chsh chfn gpasswd chage newuidmap newgidmap \
      useradd usermod userdel groupadd groupmod groupdel chpasswd \
      pwconv pwunconv grpconv grpunconv vipw vigr; do
      rm -f "/sysroot/usr/bin/${command}" "/sysroot/usr/sbin/${command}"
    done
    
    
    
    rm -f /sysroot/usr/bin/ldd /sysroot/usr/bin/sotruss /sysroot/usr/bin/tzselect \
      /sysroot/usr/bin/xtrace /sysroot/usr/bin/psl-make-dafsa \
      /sysroot/usr/bin/e2scrub /sysroot/usr/bin/e2scrub_all \
      /sysroot/etc/pki/tls/misc/CA.pl /sysroot/etc/pki/tls/misc/tsget.pl
    rm -f /sysroot/usr/lib/systemd/system/e2scrub*.service \
      /sysroot/usr/lib/systemd/system/e2scrub*.timer
    
    
    
    install -Dm644 "%{datadir}/%{os-id}/keys/update/import-pubring.pgp" \
      /sysroot%{indep-libdir}/systemd/import-pubring.pgp

  - |
    
    
    while read -r path rest; do
      case "$path" in ''|'#'*) continue ;; esac
      rm -f "/sysroot${path}"
    done < /usr/share/beamline/policy/base-user-tools.txt

  - |
    
    
    while read -r path rest; do
      case "$path" in ''|'#'*) continue ;; esac
      rm -f "/sysroot${path}"
    done < "%{libexecdir}/%{os-id}-image-tools/base-installer.txt"

  - |
    
    
    
    while read -r path rest; do
      case "$path" in ''|'#'*) continue ;; esac
      rm -f "/sysroot${path}"
      dir="${path%/*}"
      while [ -n "${dir}" ] && rmdir "/sysroot${dir}" 2>/dev/null; do dir="${dir%/*}"; done
    done < /usr/share/beamline/policy/base-virtualization.txt

  - |
    
    
    
    
    python3 "%{libexecdir}/%{os-id}-image-tools/prune-tree.py" --tree /sysroot \
      "%{libexecdir}/%{os-id}-image-tools/prune/base.txt" \
      "%{libexecdir}/%{os-id}-image-tools/prune/base-devel.txt"

  - |
    
    
    
    
    
    borrowed="$(cd /extension-sysusers%{datadir}/%{os-id}/extension-sysusers && find . -name '*.conf' | sort)"
    for conf in ${borrowed}; do
      install -m644 "/extension-sysusers%{datadir}/%{os-id}/extension-sysusers/${conf}" \
        "/sysroot/usr/lib/sysusers.d/beamline-extension-$(basename "${conf}")"
    done
    
    mkdir -p "%{image-scratch}"
    for conf in /sysroot%{indep-libdir}/sysusers.d/*.conf; do
      while IFS= read -r line; do
        case "${line}" in "g empower "*) ;; *) printf '%s\n' "${line}" ;; esac
      done < "${conf}" > "%{image-scratch}/sysusers.conf"
      install -m644 "%{image-scratch}/sysusers.conf" "${conf}"
    done
    
    
    
    
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
    
    while IFS=: read -r name _ uid _ _ _ shell; do
      [ "${name}" = root ] || continue
      [ "${uid}" = 0 ] && [ "${shell}" = /usr/bin/nologin ] || { echo "root: uid ${uid}, shell ${shell}" >&2; exit 1; }
    done < /sysroot/etc/passwd
    while IFS=: read -r name password _; do
      [ "${name}" = root ] || continue
      case "${password}" in '!'*) ;; *) echo "root is not locked" >&2; exit 1 ;; esac
    done < /sysroot/etc/shadow
    
    while IFS=: read -r name _; do
      [ "${name}" != empower ] || { echo "the empower group exists" >&2; exit 1; }
    done < /sysroot/etc/group
    [ ! -e /sysroot%{datadir}/polkit-1/rules.d/empower.rules ] || { echo "empower.rules exists" >&2; exit 1; }

  - systemctl --root=/sysroot preset-all

  - |
    
    
    
    rm -f /sysroot/etc/machine-id
    printf 'uninitialized\n' > /sysroot/etc/machine-id
    chmod 0444 /sysroot/etc/machine-id
    
    
    
    
    printf 'TIMESTAMP_NSEC=%s000000000\n' "%{source-date-epoch}" > /sysroot/etc/.updated

  - |
    
    
    find /sysroot/var -mindepth 1 -delete
    mkdir -p /sysroot/data
    
    
    mkdir -p /sysroot/efi /sysroot/boot

  - |
    
    
    
    
    
    
    
    
    
    
    
    union="%{image-scratch}/linker-cache"
    mkdir -p "${union}/etc/ld.so.conf.d"
    for tree in /sysroot /extension-content/*; do
      for conf in "${tree}"/etc/ld.so.conf.d/*.conf; do
        if [ -e "${conf}" ]; then
          cp --update=none "${conf}" "${union}/etc/ld.so.conf.d/"
        fi
      done
    done
    
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
