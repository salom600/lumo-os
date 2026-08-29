#!/usr/bin/env bash
# Interactive local boot of a Lumo ISO (BIOS+UEFI hybrid) in QEMU.
set -euo pipefail
ISO="${1:?usage: qemu-boot.sh <iso>}"
MEM="${LUMO_QEMU_MEM:-2048}"
exec qemu-system-x86_64 \
  -accel kvm:tcg -cpu max -smp 4 -m "$MEM" \
  -cdrom "$ISO" -boot d \
  -device virtio-net-pci,netdev=n0 -netdev user,id=n0 \
  -display sdl,gl=off
