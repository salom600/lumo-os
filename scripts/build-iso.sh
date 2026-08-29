#!/usr/bin/env bash
# Build the Lumo OS hybrid ISO (BIOS + UEFI) from Debian trixie using mmdebstrap.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="$HERE/build"
ROOTFS="$BUILD/rootfs"
ISOROOT="$BUILD/isosystem"
DEBS="$BUILD/debs"
VERSION="$(dpkg-parsechangelog -l "$HERE/packages/lumo-theme/debian/changelog" -S Version 2>/dev/null || echo 1.0)"
ISO_NAME="lumo-os-${VERSION}-amd64.iso"
MIRROR="${LUMO_MIRROR:-http://deb.debian.org/debian}"
SUITE="${LUMO_SUITE:-trixie}"

export DEBIAN_FRONTEND=noninteractive
rm -rf "$ROOTFS" "$ISOROOT"; mkdir -p "$ROOTFS" "$ISOROOT" "$BUILD"

lists() { grep -vE '^\s*(#|$)' "$1" | tr '\n' ' '; }
INCLUDE="$(lists "$HERE/config/package-lists/base.list") $(lists "$HERE/config/package-lists/desktop.list") $(lists "$HERE/config/package-lists/apps.list") $(lists "$HERE/config/package-lists/firmware.list") $(lists "$HERE/config/package-lists/installer.list")"

echo "==> [1/6] Bootstrapping Debian $SUITE (mmdebstrap)"
mmdebstrap \
  --architectures=amd64 --mode=root --variant=apt \
  --components="main contrib non-free non-free-firmware" \
  --setup-hook='mkdir -p "$1"/etc/dpkg/dpkg.cfg.d && printf "path-exclude=/usr/share/doc/*\npath-include=/usr/share/doc/*/copyright\npath-exclude=/usr/share/man/*\npath-exclude=/usr/share/groff/*\n" > "$1"/etc/dpkg/dpkg.cfg.d/01-lumo-slim' \
  --include="$(echo $INCLUDE)" \
  --customize-hook="copy-in $DEBS /root/lumo-debs" \
  --customize-hook="copy-in $HERE/scripts/chroot-setup.sh /root/chroot-setup.sh" \
  --customize-hook="chroot \"\$1\" /bin/bash /root/chroot-setup.sh" \
  --customize-hook="rm -rf \"\$1\"/root/lumo-debs \"\$1\"/root/chroot-setup.sh" \
  "$SUITE" "$ROOTFS" "$MIRROR"

echo "==> [2/6] Extracting kernel and initrd"
mkdir -p "$ISOROOT/live"
cp "$ROOTFS"/boot/vmlinuz-* "$ISOROOT/live/vmlinuz"
cp "$ROOTFS"/boot/initrd.img-* "$ISOROOT/live/initrd"

echo "==> [3/6] Creating squashfs (zstd)"
mksquashfs "$ROOTFS" "$ISOROOT/live/filesystem.squashfs" \
  -comp zstd -Xcompression-level 18 -noappend -no-progress >/dev/null

echo "==> [4/6] Writing GRUB config and theme"
mkdir -p "$ISOROOT/boot/grub"
cp -r "$HERE/config/grub/theme" "$ISOROOT/boot/grub/theme" 2>/dev/null || true
install -m 0644 "$HERE/config/grub/grub.cfg" "$ISOROOT/boot/grub/grub.cfg"
if [ -f "$HERE/packages/lumo-theme/usr/share/lumo/wallpapers/lumo-aurora-dark.png" ]; then
  install -m 0644 "$HERE/packages/lumo-theme/usr/share/lumo/wallpapers/lumo-aurora-dark.png" "$ISOROOT/boot/grub/theme/bg.png" 2>/dev/null || true
fi

echo "==> [5/6] Generating hybrid ISO"
grub-mkrescue -o "$BUILD/$ISO_NAME" "$ISOROOT" \
  -- -volid "LUMO_OS_${VERSION}" -joliet on -compliance no_emulation_no_img

echo "==> [6/6] Reports"
sha256sum "$BUILD/$ISO_NAME" > "$BUILD/$ISO_NAME.sha256"
chroot "$ROOTFS" dpkg-query -W -f='${Package}\t${Version}\n' | sort > "$BUILD/package-list.txt"
{ echo "ISO: $ISO_NAME"; du -h "$BUILD/$ISO_NAME"; \
  echo "Squashfs size:"; du -h "$ISOROOT/live/filesystem.squashfs"; \
  echo "Installed rootfs size:"; du -sh "$ROOTFS"; } > "$BUILD/build-report.txt"
cat "$BUILD/build-report.txt"
echo "DONE: $BUILD/$ISO_NAME"
