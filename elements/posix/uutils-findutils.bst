# SPDX-License-Identifier: MIT

kind: manual
description: uutils findutils, built and tested from its designated HEAD
build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/buildsystem-rust.bst
- build-tools/test-users.bst
depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-minimal.bst
config:
  build-commands:
  - cargo test --frozen --workspace
  - cargo build --release --frozen --workspace
  install-commands:
  - install -Dm755 target/release/find "%{install-root}%{bindir}/find"
  - install -Dm755 target/release/xargs "%{install-root}%{bindir}/xargs"
sources:
- kind: git
  url: github:uutils/findutils.git
  track: main
  ref-format: git-describe
- kind: cargo
  url: crates:crates
