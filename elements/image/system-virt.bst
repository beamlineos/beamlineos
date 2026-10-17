# SPDX-License-Identifier: MIT

kind: script
description: |
  The Virt SYSTEM image (docs/spec.md §13, §14; docs/decisions.md D47): the finished root as
  EROFS, labelled from the policy's file contexts (docs/security.md §19.1), plus its
  dm-verity hash tree. systemd-repart builds both offline and splits them out:
  system.root.raw, system.root-verity.raw, and system.json, whose root hash
  image/uki-virt.bst puts into the signed command line. File modes BuildStream cannot carry
  are restored on a copy of the tree first (docs/decisions.md D31), in %{image-scratch} outside
  the FUSE-staged sandbox root (D57).

(@):
- include/image/permissions.yml
- include/image/scratch.yml

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
- junctions/freedesktop-sdk.bst:components/systemd.bst
- junctions/freedesktop-sdk.bst:components/python3.bst
- junctions/freedesktop-sdk.bst:components/erofs-utils.bst
- image/repart-system.bst
- image/permissions.bst
- image/image-tools.bst
- filename: image/root-virt.bst
  config:
    location: /sysroot

variables:
  
  
  system-seed: 2f9a6c1e-5b3d-4e8f-9a07-6d1c8b4e2a35

environment:
  SOURCE_DATE_EPOCH: '%{source-date-epoch}'
  
  
  SYSTEMD_REPART_MKFS_OPTIONS_EROFS: --file-contexts=%{image-scratch}/root/etc/selinux/beamline/contexts/files/file_contexts
  TMPDIR: '%{image-scratch}/tmp'

config:
  commands:
  - |
    mkdir -p "%{image-scratch}/tmp"
    cp -a /sysroot "%{image-scratch}/root"
    %{apply-permissions}
    apply_permissions "%{image-scratch}/root"
    python3 "%{libexecdir}/%{os-id}-image-tools/check-policy.py" --artifact "%{image-scratch}/root"

  - |
    systemd-repart \
      --offline=yes \
      --dry-run=no \
      --empty=create \
      --size=auto \
      --seed=%{system-seed} \
      --definitions="%{datadir}/%{os-id}/repart/system" \
      --copy-source="%{image-scratch}/root" \
      --split=yes \
      --json=pretty \
      "%{image-scratch}/system.raw" > "%{image-scratch}/system.json"
    install -m644 -t "%{install-root}" "%{image-scratch}/system.json" \
      "%{image-scratch}/system.root.raw" "%{image-scratch}/system.root-verity.raw"
    python3 - "%{install-root}/system.json" <<'EOF'
    import json, sys
                                                             
    hashes = {p["roothash"] for p in json.load(open(sys.argv[1])) if p.get("roothash") not in (None, "", "-")}
    assert len(hashes) == 1, hashes
    print("SYSTEM root hash:", *hashes)
    EOF
