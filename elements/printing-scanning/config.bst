# SPDX-License-Identifier: MIT

kind: import
description: CUPS configuration and state on DATA, moved from desktop-gnome (D58, D65).

depends:
- junctions/freedesktop-sdk.bst:components/cups-daemon.bst

public:
  bst:
    overlap-whitelist:
    - '%{sysconfdir}/cups/cups-files.conf'

sources:
- kind: local
  path: files/printing-scanning
