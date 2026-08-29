# Building Lumo OS locally

## Requirements

- Debian 12/13 host (or any Linux with the tools below)
- ~15 GB free disk, root access
- Packages:

```bash
sudo apt install git make mmdebstrap squashfs-tools xorriso \
  grub-pc-bin grub-efi-amd64-bin mtools dosfstools e2fsprogs arch-test debootstrap
```

## One-shot build

```bash
git clone https://github.com/salom600/lumo-os.git
cd lumo-os
sudo ./build.sh
# -> build/lumo-os-1.0-amd64.iso
```

Or step by step:

```bash
./scripts/build-debs.sh     # builds all packages/lumo-* into build/debs/
sudo ./scripts/build-iso.sh # mmdebstrap rootfs -> squashfs -> hybrid ISO
```

Environment knobs:

- `LUMO_SUITE=trixie` - Debian suite (default: trixie = stable)
- `LUMO_MIRROR=http://deb.debian.org/debian` - mirror

## Test in QEMU

```bash
scripts/tests/qemu-boot.sh build/lumo-os-1.0-amd64.iso         # interactive
scripts/tests/qemu-smoke.sh build/lumo-os-1.0-amd64.iso        # automated test:
# boots with lumo.test=1, autologins, captures screenshots of every shell
# surface, measures RAM/CPU, writes build/validation-report.md
```

Notes:

- `qemu-smoke.sh` extracts the kernel/initrd from the ISO and boots them
  directly with `-kernel/-initrd` so the test-mode cmdline can be injected
  without modifying the ISO.
- KVM is used when available; on GitHub runners it falls back to TCG
  (boot takes ~5-10 min there).

## CI

Push to `main` (or run the workflow manually) - `.github/workflows/build.yml`:

1. **lint** - syntax checks for shell/python/XML/JSON/QML + packaging sanity
2. **build** - produces the ISO + sha256 + package list + build log
3. **test** - QEMU boot, SSH-driven validation, screenshots, RAM/CPU report
4. **release** - publishes the ISO + checksums as a GitHub release

All artifacts are uploaded (30-day retention); the release keeps them permanently.
