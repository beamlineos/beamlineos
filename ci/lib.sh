# SPDX-License-Identifier: MIT
# shellcheck shell=sh
#
# Shared helpers for ci/*. Every script works from macOS (delegating BuildStream work to
# the Lima builder VM) and from a Linux builder or hosted runner (running directly).

set -eu

REPO="$(cd "$(dirname "$0")/.." && pwd)"
LIMA_INSTANCE="${LIMA_INSTANCE:-myos-builder}"

case "$(uname -m)" in
    arm64 | aarch64) HOST_ARCH=aarch64 ;;
    x86_64 | amd64) HOST_ARCH=x86_64 ;;
    *) HOST_ARCH="$(uname -m)" ;;
esac
# Builds are native-only: the image architecture is the builder's architecture.
ARCH="${ARCH:-$HOST_ARCH}"
# shellcheck disable=SC2034 # used by the scripts that source this file
OUT="$REPO/out/$ARCH/virt"

log() { printf '==> %s\n' "$*" >&2; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }
is_macos() { [ "$(uname -s)" = Darwin ]; }

# Run a command in the build environment, from the repository root.
in_builder() {
    if is_macos; then
        limactl shell --workdir "$REPO" "$LIMA_INSTANCE" -- "$@"
    else
        (cd "$REPO" && "$@")
    fi
}

bst_run() {
    in_builder bst --option arch "$ARCH" "$@"
}
