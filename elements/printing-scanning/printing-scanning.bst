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


- junctions/freedesktop-sdk.bst:components/libtool.bst
