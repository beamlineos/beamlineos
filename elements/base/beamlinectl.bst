# SPDX-License-Identifier: MIT
kind: manual
description: Beamline's confined extension control service and its unprivileged varlink client.

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/buildsystem-rust.bst
- junctions/freedesktop-sdk.bst:components/systemd.bst

depends:
- base/runtime.bst

config:
  build-commands:
  - cargo build --release --frozen --offline
  - cargo test --release --frozen --offline
  install-commands:
  - install -Dm755 target/release/beamlinectl "%{install-root}%{bindir}/beamlinectl"
  - install -Dm755 target/release/beamlinectld "%{install-root}%{libexecdir}/beamlinectld"
  - install -Dm644 org.beamline.Extensions.varlink "%{install-root}%{datadir}/varlink/org.beamline.Extensions.varlink"

sources:
- kind: local
  path: files/beamlinectl
- kind: cargo
  url: crates:crates
