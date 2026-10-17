# SPDX-License-Identifier: MIT

kind: script
description: |
  Debian's signed shim, MokManager and fallback (docs/decisions.md D113), taken from Debian's
  packages as published, into /usr/share/beamline/secure-boot/shim:
    shim<arch>.efi  the first stage: Microsoft's UEFI CA signed it, so firmware holding Microsoft's
                    keys starts it. It verifies its second stage, grub<arch>.efi in its own
                    directory, against db, Debian's certificate built into it, and the MOKs.
    mm<arch>.efi    MokManager, which shim starts when the second stage is not trusted
    fb<arch>.efi    the fallback, which creates boot entries from BOOT<ARCH>.CSV files
  The build checks shim's signature against Microsoft's UEFI CAs and the name of its second stage.

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
- junctions/freedesktop-sdk.bst:components/python3.bst
- junctions/freedesktop-sdk.bst:components/openssl.bst
- junctions/freedesktop-sdk.bst:components/sbsigntools-maybe.bst
- boot/debian-shim-signed.bst
- boot/debian-shim-helpers.bst
- boot/microsoft-uefi-ca-2011.bst
- boot/microsoft-uefi-ca-2023.bst

variables:
  upstream: '%{datadir}/%{os-id}/secure-boot/upstream'
  shim-dir: '%{install-root}%{datadir}/%{os-id}/secure-boot/shim'

config:
  commands:
  - |
    install -d "%{shim-dir}"
    
    python3 - "%{upstream}" "%{shim-dir}" "%{efi-arch}" <<'PY'
    import io, sys, tarfile
    upstream, out, arch = sys.argv[1:]
    def members(deb):
        blob = open(deb, "rb").read()
        assert blob[:8] == b"!<arch>\n", deb
        at = 8
        while at < len(blob):
            name = blob[at:at + 16].decode().strip().rstrip("/")
            size = int(blob[at + 48:at + 58])
            yield name, blob[at + 60:at + 60 + size]
            at += 60 + size + (size & 1)
    wanted = {f"shim{arch}.efi", f"mm{arch}.efi", f"fb{arch}.efi"}
    for deb in ("shim-signed.deb", "shim-helpers.deb"):
        for name, data in members(f"{upstream}/{deb}"):
            if not name.startswith("data.tar"):
                continue
            with tarfile.open(fileobj=io.BytesIO(data)) as tar:
                for member in tar.getmembers():
                    base = member.name.rsplit("/", 1)[-1]
                    if base.endswith(".efi.signed") and base[:-len(".signed")] in wanted:
                        target = base[:-len(".signed")]
                        open(f"{out}/{target}", "wb").write(tar.extractfile(member).read())
                        wanted.discard(target)
    assert not wanted, f"missing from Debian's packages: {sorted(wanted)}"
                                                                                          
    shim = open(f"{out}/shim{arch}.efi", "rb").read()
    assert f"grub{arch}.efi".encode("utf-16-le") in shim, "unexpected second-stage name"
    PY
    chmod 0644 "%{shim-dir}"/*.efi

  - |
    
    for ca in microsoft-uefi-ca-2011 microsoft-uefi-ca-2023; do
      openssl x509 -inform DER -in "%{upstream}/${ca}.crt" -out "/tmp/${ca}.pem"
    done
    sbverify --cert /tmp/microsoft-uefi-ca-2011.pem "%{shim-dir}/shim%{efi-arch}.efi" ||
      sbverify --cert /tmp/microsoft-uefi-ca-2023.pem "%{shim-dir}/shim%{efi-arch}.efi"
