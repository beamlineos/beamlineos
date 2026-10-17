# SPDX-License-Identifier: MIT

kind: manual
description: uutils diffutils, built and tested from its designated HEAD
build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/buildsystem-rust.bst
- junctions/freedesktop-sdk.bst:components/ed.bst
- junctions/freedesktop-sdk.bst:components/patch.bst
depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-minimal.bst
config:
  build-commands:
  - cargo test --frozen --workspace
  - cargo build --release --frozen --workspace
  install-commands:
  - install -Dm755 target/release/diffutils "%{install-root}%{bindir}/diffutils"
  - for name in cmp diff diff3 sdiff; do ln -s diffutils "%{install-root}%{bindir}/${name}"; done
sources:
- kind: git
  url: github:uutils/diffutils.git
  track: main
  ref-format: git-describe
- kind: cargo
  url: crates:crates
