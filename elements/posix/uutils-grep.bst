# SPDX-License-Identifier: MIT

kind: manual
description: uutils grep, built and tested from its designated HEAD
build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/buildsystem-rust.bst
depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-minimal.bst
runtime-depends:
- base/base.bst

config:
  build-commands:
  - cargo test --frozen --workspace
  - cargo build --release --frozen --workspace
  install-commands:
  - install -Dm755 target/release/grep "%{install-root}%{bindir}/grep"
sources:
- kind: git
  url: github:uutils/grep.git
  track: main
  ref-format: git-describe
- kind: cargo
  url: crates:crates

public:
  bst:
    
    
    overlap-whitelist:
    - /usr/bin/grep
    - /usr/lib/debug/usr/bin/grep.debug
