# SPDX-License-Identifier: MIT
# A sibling is eligible only after its own native test suite passes (§7.2, D63).
kind: manual
description: uutils bsdutils, built and tested from its designated HEAD
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
  - install -Dm755 target/release/bsdutils "%{install-root}%{bindir}/bsdutils"
  - for name in renice; do ln -s bsdutils "%{install-root}%{bindir}/${name}"; done
sources:
- kind: git
  url: github:uutils/bsdutils.git
  track: main
  ref-format: git-describe
- kind: cargo
  url: crates:crates

public:
  bst:
    # This user command is removed from the finished base; its library artifact
    # stages first via base/base.bst, then the preferred uutils implementation.
    overlap-whitelist:
    - /usr/bin/renice
