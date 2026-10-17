# SPDX-License-Identifier: MIT
# shellcheck shell=sh




set -eu

REPO="$(cd "$(dirname "$0")/.." && pwd)"
LIMA_INSTANCE="${LIMA_INSTANCE:-myos-builder}"

case "$(uname -m)" in
    arm64 | aarch64) HOST_ARCH=aarch64 ;;
    x86_64 | amd64) HOST_ARCH=x86_64 ;;
    *) HOST_ARCH="$(uname -m)" ;;
esac

ARCH="${ARCH:-$HOST_ARCH}"
# shellcheck disable=SC2034 # used by the scripts that source this file
OUT="$REPO/out/$ARCH/virt"

log() { printf '==> %s\n' "$*" >&2; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }
is_macos() { [ "$(uname -s)" = Darwin ]; }


in_builder() {
    if is_macos; then
        limactl shell --workdir "$REPO" "$LIMA_INSTANCE" -- "$REPO/ci/python-tools" "$@"
    else
        (cd "$REPO" && "$REPO/ci/python-tools" "$@")
    fi
}

bst_run() {
    in_builder bst --option arch "$ARCH" "$@"
}
