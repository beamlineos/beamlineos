# SPDX-License-Identifier: MIT

kind: stack
description: Avahi's native runtime in the base, with Beamline's filtered GLib (D65).

depends:
- base/avahi-files.bst
- base/glib.bst
- junctions/freedesktop-sdk.bst:components/avahi-libs.bst
- junctions/freedesktop-sdk.bst:components/avahi-manifest.bst
- junctions/freedesktop-sdk.bst:components/dbus.bst
- junctions/freedesktop-sdk.bst:components/libdaemon.bst
