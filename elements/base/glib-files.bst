# SPDX-License-Identifier: MIT

kind: script
description: |
  GLib without its developer scripts (docs/spec.md §5.2, D61). Reuse the pinned
  gnome-build-meta artifact; Python is only needed to build GLib and run these tools.

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
- filename: base/glib-artifact.bst
  config:
    location: /input

config:
  commands:
  - cp -a /input/. "%{install-root}/"
  - |
    rm -f "%{install-root}%{bindir}/gdbus-codegen" \
      "%{install-root}%{bindir}/glib-genmarshal" \
      "%{install-root}%{bindir}/glib-mkenums" \
      "%{install-root}%{bindir}/glib-gettextize" \
      "%{install-root}%{bindir}/gtester-report"
    rm -rf "%{install-root}%{datadir}/glib-2.0/codegen"
    rm -rf "%{install-root}%{datadir}/glib-2.0/gdb"
    rm -f "%{install-root}%{datadir}/gdb/auto-load%{libdir}/libglib-2.0.so."*-gdb.py \
      "%{install-root}%{datadir}/gdb/auto-load%{libdir}/libgobject-2.0.so."*-gdb.py \
      "%{install-root}%{libdir}/libgirepository-2.0.so"

public:
  bst:
    integration-commands:
    - glib-compile-schemas %{datadir}/glib-2.0/schemas
    - |
      if [ -d "%{libdir}/gio/modules" ]; then
        gio-querymodules "%{libdir}/gio/modules"
      fi
    
    
    overlap-whitelist:
    - '%{bindir}/gapplication'
    - '%{bindir}/gdbus'
    - '%{bindir}/gi-*-*'
    - '%{bindir}/gio'
    - '%{bindir}/gio-querymodules'
    - '%{bindir}/glib-compile-*'
    - '%{bindir}/gobject-query'
    - '%{bindir}/gresource'
    - '%{bindir}/gsettings'
    - '%{bindir}/gtester'
    - '%{libexecdir}/gio-launch-desktop'
    - '%{libdir}/libgio-2.0.so.*'
    - '%{libdir}/libglib-2.0.so.*'
    - '%{libdir}/libgmodule-2.0.so.*'
    - '%{libdir}/libgobject-2.0.so.*'
    - '%{libdir}/libgthread-2.0.so.*'
    - '%{libdir}/libgirepository-2.0.so.*'
    - '%{libdir}/girepository-1.0/*.typelib'
    - '%{libdir}/glib-2.0/**'
    - '%{datadir}/glib-2.0/**'
    - '%{datadir}/bash-completion/completions/gapplication'
    - '%{datadir}/bash-completion/completions/gdbus'
    - '%{datadir}/bash-completion/completions/gio'
    - '%{datadir}/bash-completion/completions/gresource'
    - '%{datadir}/bash-completion/completions/gsettings'
    - '%{datadir}/gettext/its/gschema.*'
    - '%{datadir}/locale/*/LC_MESSAGES/glib20.mo'
    - '%{licensedir}/gnome/glib/**'
