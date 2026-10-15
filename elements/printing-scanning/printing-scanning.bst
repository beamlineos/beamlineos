# SPDX-License-Identifier: MIT

kind: stack
description: |
  CUPS daemon, filters, backends and client commands, printer support, and SANE backends
  including driverless AirScan (§7.4, D64, D65). HPLIP is excluded. Depends only on the base.

depends:
- printing-scanning/config.bst
- junctions/freedesktop-sdk.bst:components/cups-daemon.bst
- junctions/gnome-build-meta.bst:core-deps/cups-pk-helper.bst
- junctions/gnome-build-meta.bst:core-deps/system-config-printer.bst
- junctions/gnome-build-meta.bst:core-deps/sane-airscan.bst
# libltdl, which libgphoto2 (SANE's camera backend) needs but does not declare; libtool's scripts
# are development files, which the composition excludes (found by the library check, D88).
- junctions/freedesktop-sdk.bst:components/libtool.bst
