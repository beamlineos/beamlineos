# SPDX-License-Identifier: MIT

kind: script
description: |
  Package paths omitted from desktop-gnome, retaining the base dmsetup and verity udev
  rules. The original artifacts and sources stay intact (D67).

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
- junctions/freedesktop-sdk.bst:components/python3.bst
- filename: desktop/pruned-files.bst
  config:
    location: /omit
- filename: base/device-mapper-files.bst
  config:
    location: /keep
- filename: desktop/libblockdev-files.bst
  config:
    location: /blockdev

variables:
  strip-binaries: ''

config:
  commands:
  - |
    python3 - "%{install-root}%{libexecdir}/beamline-image-tools/desktop-pruned-exclusions.txt" <<'PYCODE'
    import os, pathlib, sys
    def paths(root):
        return {os.path.relpath(os.path.join(directory, name), root)
                for directory, dirs, files in os.walk(root)
                for name in files + [d for d in dirs if os.path.islink(os.path.join(directory, d))]}
    omitted = paths("/omit") - paths("/keep")
    omitted.update(path for path in paths("/blockdev")
                   if pathlib.PurePosixPath(path).name.startswith("libbd_lvm")
                   or path in ("usr/bin/lvm-cache-stats", "etc/libblockdev/3/conf.d/10-lvm-dbus.cfg"))
    target = pathlib.Path(sys.argv[1])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# SPDX-License-Identifier: MIT\n" +
                      "".join("/" + path + "\n" for path in sorted(omitted)))
    PYCODE
