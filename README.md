# Lumo OS

**Featherlight. Fearless. Beautiful.**

Lumo OS is a modern, ultra-light Linux distribution built on **Debian 13 (trixie) Stable**,
with a custom, unified desktop experience called **Lumo Shell**. It is designed to run well
on very old hardware (2007), shine on mid-range machines (2016), and fly on modern
hardware (2026) — while giving your games, browser and apps every possible resource
instead of wasting them on background bloat.

<p align="center">
  <img src="docs/img/design-reference.png" alt="Lumo OS design reference" width="800"/>
</p>

---

## Identity

| | |
|---|---|
| **Name** | Lumo OS |
| **Codename** | 1.0 "Aurora" |
| **Base** | Debian 13 trixie (Stable) |
| **Session** | Lumo Shell (labwc + Waybar + Lumo Tools, Wayland) |
| **Greeter** | Lumo Greeter (SDDM + custom QML theme) |
| **Installer** | Calamares, fully branded |
| **Accent** | `#3584e4` (8 accent choices in Settings) |
| **Fonts** | Inter (UI), Noto Sans / Noto Sans Arabic (full RTL + Arabic support) |
| **Icons** | Papirus |
| **Target** | < 150 MB idle desktop session RAM (where technically possible) |

## Lumo Shell — assembled, not forked

Lumo Shell is **not** LXDE, not Xfce, and not a re-theme of either. It is an original,
cohesive desktop assembled from modern Wayland building blocks, with custom
applications providing its identity:

- **labwc** — tiny wlroots compositor (floating, snap, rounded corners)
- **Lumo Bar** — Waybar top status bar (Activities · centered clock · network/battery/volume/power)
- **Lumo Dock** — floating left dock (pinned apps + live taskbar + trash)
- **Lumo Launcher** — glassy full-screen app launcher with instant search
- **Lumo Quick Settings** — top-right control center (Wi-Fi, Bluetooth, Game Mode, volume, brightness)
- **Lumo Calendar / Power / Welcome** — matching glass popups
- **Lumo Store** — real software center (AppStream + PackageKit: install, remove, update)
- **Lumo Settings** — real settings app (Wi-Fi, Bluetooth, Displays, Sound, Keyboard, Users, Drivers…)
- **Lumo Greeter** — custom SDDM QML login/lock screen
- **Notifications** — mako, themed to match
- **Apps** — Nautilus (Files), Foot (terminal), Firefox ESR, GNOME Text Editor, Loupe, mpv

Every button is wired to a real backend (nmcli, pactl, bluetoothctl, PackageKit,
sysfs, timedatectl, AccountsService…). **No fake UI.**

## Feature highlights

- **Ultra-light**: labwc session, zram, tuned sysctl, volatile-size-capped journald,
  no redundant daemons. Measured RAM is reported on every CI build.
- **Gaming**: Mesa + Vulkan, XWayland, GameMode, Game Mode CPU-governor toggle in
  Quick Settings, optional Steam / Wine / MangoHud / controller tools via Lumo Store.
- **Hardware**: BIOS **and** UEFI boot, full firmware set (non-free-firmware),
  Safe Graphics fallback, VM support (SPiCE/QEMU agents), printer stack included.
- **Arabic + RTL**: full Noto Arabic fonts, RTL-capable GTK apps, Arabic keyboard layouts.
- **Light/Dark modes** with wallpaper switching and 8 accent colors.
- **Reproducible CI**: one GitHub Actions run produces the ISO, checksums, package list,
  QEMU boot test, screenshots, RAM/CPU report and a PASS/FAIL validation report.

## Repository layout

```
lumo-os/
├── build.sh                  # one-shot local build entry point
├── Makefile                  # debs / iso / test targets
├── config/package-lists/     # Debian package selections
├── packages/
│   ├── lumo-theme/           # wallpapers, GTK/waybar CSS, palette, branding
│   ├── lumo-defaults/        # labwc, waybar, SDDM session, portals, services, defaults
│   ├── lumo-tools/           # launcher, quick settings, calendar, power, welcome, shot
│   ├── lumo-store/           # AppStream + PackageKit software center
│   ├── lumo-settings/        # settings application
│   ├── lumo-greeter/         # SDDM QML theme
│   ├── lumo-installer/       # Calamares config + branding + post-install hooks
│   └── lumo-live/            # live session bootstrap (user, autologin, test mode)
├── scripts/                  # build scripts (debs, ISO, chroot setup)
├── scripts/tests/            # QEMU boot smoke test + screenshot collection
├── tests/                    # local validation (lint) tooling
├── ci/                       # CI helper notes
└── docs/                     # architecture, design, building, validation
```

## Build it yourself

```bash
sudo apt install git make mmdebstrap squashfs-tools xorriso \
     grub-pc-bin grub-efi-amd64-bin mtools dosfstools e2fsprogs arch-test
git clone https://github.com/salom600/lumo-os.git
cd lumo-os
sudo ./build.sh            # -> build/lumo-os-<version>-amd64.iso
```

Or push to GitHub — Actions builds everything automatically (see `.github/workflows/build.yml`).

## Test the ISO in QEMU

```bash
scripts/tests/qemu-boot.sh build/lumo-os-*-amd64.iso     # interactive boot
scripts/tests/qemu-smoke.sh build/lumo-os-*-amd64.iso    # automated test + screenshots
```

## License

Lumo OS original code and assets: **GPL-3.0-or-later**.
All upstream Debian packages keep their own licenses; firmware from
`non-free-firmware` is redistributed under Debian's policy.
