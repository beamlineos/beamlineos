# SPDX-License-Identifier: MIT

kind: import
description: |
  The installer's own configuration (docs/decisions.md D106, D113), shipped by the installer
  extension only: its target and service, systemd-sysinstall's partition definitions for the
  target disk, and the target ESP's loader.conf.

sources:
- kind: local
  path: files/installer/systemd
  directory: usr/lib/systemd
- kind: local
  path: files/installer/repart.sysinstall.d
  directory: usr/lib/repart.sysinstall.d
- kind: local
  path: files/installer/esp
  directory: usr/lib/beamline/esp
