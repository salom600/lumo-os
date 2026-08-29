#!/usr/bin/env bash
# Lumo OS one-shot build entry point (run as root or with sudo)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

if [[ $EUID -ne 0 ]]; then
  echo "Re-running with sudo (mmdebstrap needs root for this mode)..."
  exec sudo -E "$0" "$@"
fi

echo "==> [1/3] Installing build dependencies"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq mmdebstrap squashfs-tools xorriso \
  grub-pc-bin grub-efi-amd64-bin mtools dosfstools e2fsprogs arch-test \
  debootstrap >/dev/null

echo "==> [2/3] Building Lumo debs"
./scripts/build-debs.sh

echo "==> [3/3] Building ISO"
./scripts/build-iso.sh
