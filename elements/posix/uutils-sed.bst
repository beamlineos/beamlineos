# SPDX-License-Identifier: MIT
# A sibling is eligible only after its own native test suite passes (§7.2, D63).
kind: manual
description: uutils sed, built and tested from its designated HEAD
build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/buildsystem-rust.bst
depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-minimal.bst
config:
  build-commands:
  - cargo test --frozen --workspace
  - cargo build --release --frozen --workspace
  install-commands:
  - install -Dm755 target/release/sed "%{install-root}%{bindir}/sed"
sources:
- kind: git
  url: github:uutils/sed.git
  track: main
  ref-format: git-describe
- kind: cargo
  url: crates:crates
