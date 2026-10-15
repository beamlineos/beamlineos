# SPDX-License-Identifier: MIT

kind: script
description: |
  A snapshot's update artifacts, as systemd-sysupdate fetches them from a channel directory
  (docs/spec.md §16, docs/decisions.md D52):
    beamline_<snapshot>.efi, beamline-dev_<snapshot>.efi   the UKIs
    beamline_<snapshot>_<uuid>.root.raw                    SYSTEM (uuid from its root hash)
    beamline_<snapshot>_<uuid>.root-verity.raw             SYSTEM's verity hash tree
    <extension>_<snapshot>.{sysext,confext}.raw            the extension images
    SHA256SUMS, SHA256SUMS.gpg                             the manifest, signed
  The manifest is signed with the development update key (docs/security.md §19.4). Ed25519
  signatures are deterministic, and gpg's clock is frozen at the key's creation time (it
  refuses to sign before it), so the signature is reproducible.

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
- junctions/freedesktop-sdk.bst:components/python3.bst
- junctions/freedesktop-sdk.bst:components/gnupg.bst
- security/keys-update.bst
- image/image-tools.bst
- filename: image/uki-virt.bst
  config:
    location: /uki
- filename: image/system-virt.bst
  config:
    location: /system
- filename: extensions/posix.bst
  config:
    location: /extensions
- filename: extensions/posix-devel.bst
  config:
    location: /extensions
- filename: extensions/printing-scanning.bst
  config:
    location: /extensions
- filename: extensions/desktop-gnome.bst
  config:
    location: /extensions
# For the path check only: the installer extension is never in the channel (D113).
- filename: extensions/installer.bst
  config:
    location: /extensions

variables:
  version: '%{snapshot-id}'

environment:
  SOURCE_DATE_EPOCH: '%{source-date-epoch}'

config:
  commands:
  - |
    # No two extensions ship one path with different content: overlayfs would show whichever
    # merged last (D88).
    python3 "%{libexecdir}/%{os-id}-image-tools/extension-paths.py" compare /extensions/*.paths

  - |
    out="%{install-root}"
    install -m644 "/uki/xbootldr/EFI/Linux/%{os-id}_%{version}.efi" "/uki/xbootldr/EFI/Linux/%{os-id}-dev_%{version}.efi" "${out}/"
    python3 - /system/system.json "${out}" "%{os-id}_%{version}" <<'EOF'
    import json, shutil, sys
    partitions, out, prefix = json.load(open(sys.argv[1])), sys.argv[2], sys.argv[3]
    for suffix, verity in (("root", False), ("root-verity", True)):
        uuid, = [p["uuid"] for p in partitions
                 if p["type"].startswith("root-") and p["type"].endswith("-verity") == verity]
        name = f"{prefix}_{uuid.replace('-', '')}.{suffix}.raw"
        shutil.copyfile(f"/system/system.{suffix}.raw", f"{out}/{name}")
        print(name)
    EOF
    for name in posix posix-devel desktop-gnome printing-scanning; do
      for kind in sysext confext; do
        install -m644 "/extensions/${name}.${kind}.raw" "${out}/${name}_%{version}.${kind}.raw"
      done
    done
    # Compatibility aliases for clients whose immutable transfer definitions still
    # name admin (D63). These are the exact signed posix bytes, not a second extension.
    for kind in sysext confext; do
      ln "${out}/posix_%{version}.${kind}.raw" "${out}/admin_%{version}.${kind}.raw"
    done

  - |
    cd "%{install-root}"
    python3 - <<'EOF'
    import hashlib, os
    with open("SHA256SUMS", "w") as f:
        for name in sorted(os.listdir(".")):
            if name != "SHA256SUMS":
                h = hashlib.sha256()
                with open(name, "rb") as g:
                    for chunk in iter(lambda: g.read(1 << 20), b""):
                        h.update(chunk)
                f.write(f"{h.hexdigest()} *{name}\n")
    EOF
    export GNUPGHOME=/work/gnupg
    mkdir -p "${GNUPGHOME}" && chmod 700 "${GNUPGHOME}"
    gpg --batch --quiet --import "%{datadir}/%{os-id}/keys/update/update-signing.sec.asc"
    created="$(gpg --batch --with-colons --list-secret-keys \
      | python3 -c 'import sys; print(next(l.split(":")[5] for l in sys.stdin if l.startswith("sec:")))')"
    gpg --batch --quiet --faked-system-time "${created}!" \
      --detach-sign --output SHA256SUMS.gpg SHA256SUMS
    gpg --batch --quiet --no-default-keyring \
      --keyring "%{datadir}/%{os-id}/keys/update/import-pubring.pgp" \
      --verify SHA256SUMS.gpg SHA256SUMS
    cat SHA256SUMS
