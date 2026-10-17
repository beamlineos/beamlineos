# SPDX-License-Identifier: MIT

kind: manual
description: uutils awk, built and tested from its designated HEAD
build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/buildsystem-rust.bst
depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-minimal.bst
config:
  build-commands:
  - cargo test --frozen --workspace
  - cargo build --release --frozen --workspace
  install-commands:
  - install -Dm755 target/release/awk "%{install-root}%{bindir}/awk"
sources:
- kind: git
  url: github:uutils/awk.git
  track: main
  ref-format: git-describe
- kind: git
  url: github:Hans-Halverson/indexmap-allocator-api.git
  track: 36852f985c01fb9f58f2d9e510655ca1dbb1f4d0
  directory: vendor/indexmap
- kind: patch
  path: files/posix/awk-vendor.patch
- kind: cargo
  url: crates:crates
