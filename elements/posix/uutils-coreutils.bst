# SPDX-License-Identifier: MIT

kind: manual
description: |
  uutils coreutils as one multicall binary with a symlink per utility (docs/spec.md §7.2).
  The only coreutils allowed in an artifact; GNU coreutils stays a build-time tool.
  Utilities that other POSIX tools provide are not linked (%{uutils-not-linked}).

build-depends:
- junctions/freedesktop-sdk.bst:public-stacks/buildsystem-rust.bst

depends:
- junctions/freedesktop-sdk.bst:public-stacks/runtime-minimal.bst

runtime-depends:
- base/base.bst

variables:
  uutils-not-linked: ''

config:
  build-commands:
  - cargo build --release --frozen --features unix

  install-commands:
  - |
    install -Dm755 target/release/coreutils "%{install-root}%{bindir}/coreutils"
    for name in $(target/release/coreutils --list); do
      case " %{uutils-not-linked} coreutils " in *" ${name} "*) continue ;; esac
      ln -s coreutils "%{install-root}%{bindir}/${name}"
    done

sources:
- kind: git
  url: github:uutils/coreutils.git
  track: main
  ref-format: git-describe
- kind: cargo
  url: crates:crates

public:
  bst:
    # This user command is removed from the finished base; its library artifact
    # stages first via base/base.bst, then the preferred uutils implementation.
    overlap-whitelist:
    - /usr/bin/more
