# SPDX-License-Identifier: MIT

kind: stack
description: |
  D-Bus broker. components/dbus.bst is included for the bus policy files under
  /usr/share/dbus-1 that dbus-broker-launch reads; the preset enables dbus-broker.

depends:
- junctions/freedesktop-sdk.bst:components/dbus-broker.bst
- junctions/freedesktop-sdk.bst:components/dbus.bst
