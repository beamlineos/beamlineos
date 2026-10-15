# SPDX-License-Identifier: MIT

kind: script
description: |
  Exact upstream package paths to omit from desktop-gnome, preserving paths also supplied
  by libcups (including its license). The original artifacts and sources stay intact (D65).

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
- junctions/freedesktop-sdk.bst:components/python3.bst
- filename: printing-scanning/desktop-omitted.bst
  config:
    location: /omit
- filename: printing-scanning/libcups-files.bst
  config:
    location: /keep

variables:
  strip-binaries: ''

config:
  commands:
  - |
    python3 - "%{install-root}%{libexecdir}/beamline-image-tools/printing-desktop-exclusions.txt" <<'PYCODE'
    import os, pathlib, sys
    def paths(root):
        return {os.path.relpath(os.path.join(directory, name), root)
                for directory, dirs, files in os.walk(root)
                for name in files + [d for d in dirs if os.path.islink(os.path.join(directory, d))]}
    target = pathlib.Path(sys.argv[1])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# SPDX-License-Identifier: MIT\n" +
                      "".join("/" + path + "\n" for path in sorted(paths("/omit") - paths("/keep"))))
    PYCODE
