# Validation Plan & Current Status

## What CI validates on every build

| # | Check | Method | Target |
|---|---|---|---|
| 1 | ISO builds | mmdebstrap+mksquashfs+grub-mkrescue exit 0 | PASS |
| 2 | ISO boots (BIOS/UEFI-capable image) | QEMU boot with serial console | kernel + systemd reach graphical target |
| 3 | Live user + autologin | SSH in via test-mode key | session exists |
| 4 | Login screen renders | sddm-greeter --test-mode screenshot | non-blank image |
| 5 | Desktop shell | grim screenshot | bar + dock + wallpaper visible |
| 6 | App launcher | launch + screenshot | overlay with app grid |
| 7 | Quick settings | launch + screenshot | tiles/sliders panel |
| 8 | Calendar / Power | launch + screenshots | popups render |
| 9 | App store | launch + screenshot | window renders with sidebar |
| 10 | Settings | launch + screenshot | 18-module UI renders |
| 11 | Terminal | foot + screenshot | terminal window |
| 12 | Failed units | `systemctl --failed` | empty |
| 13 | **Session RAM (idle)** | sum of PSS of the session user's processes via `smaps_rollup`, measured before any test app runs | target <= 150 MB (**hard gate**) |
| 14 | System RAM (whole OS) | `MemTotal - MemAvailable` after `drop_caches` (includes kernel + daemons + live media) | reported (INFO/NEAR/MISS) |
| 15 | CPU idle | `vmstat 1 5`, idle column | > 85% idle |
| 16 | Boot time | `systemd-analyze` | reported |
| 17 | **Screenshot integrity** | app alive at capture (status.txt) + md5 uniqueness; any shot pixel-identical to the desktop frame fails | no duplicates / no dead apps |

### Why two RAM metrics?

The product target "basic desktop session < 150 MB" is measured as the sum of
proportional set sizes (PSS) of every process owned by the session user
(compositor, bar, notifications, wallpaper, idle/audio daemons, portals).
Shared pages are counted fractionally, so this is the honest cost of the
desktop session itself. The whole-OS "used" number additionally contains the
kernel, slab, and every boot-time system daemon; on live media it also
counts tmpfs writes. It is reported for transparency but is not the product
metric.

### False-pass guards (added after run 30/31 review)

- Runs 30/31 technically passed while every GTK4 popup screenshot was
  byte-identical to the desktop frame: the layer-shell library was loaded
  after libwayland, so `gtk_layer_init_for_window()` silently failed and no
  window ever mapped. CI now (a) preloads `libgtk4-layer-shell.so.0` in
  every Lumo GTK4 entry point (`/usr/bin/lumo-*` are wrappers around
  `/usr/libexec/lumo/*`), (b) records app liveness at capture time,
  (c) fails any screenshot that is pixel-identical to another.
- The greeter shot previously never ran (empty binary path in the shot
  script); the guest search now covers `/usr/libexec/sddm/sddm-greeter`.

Latest report: see the `lumo-os-test-evidence` artifact of the newest
Actions run, and the published GitHub release notes.

## Design comparison method

1. CI captures screenshots of: greeter, desktop, launcher, quick settings,
   calendar, power, store, settings, terminal.
2. Each screenshot is compared against `docs/img/design-reference.png`
   (vision analysis + layout/color comparison) by the maintainer; fixes
   land as CSS/config changes and the loop repeats.
3. `docs/DESIGN.md` records the token mapping between the reference and
   the implementation.

## Known limitations (v1.0-alpha, honest list)

- labwc v1 has no on-screen workspace indicator (workspaces unsupported by
  the compositor version in trixie); window snapping, fullscreen and
  Alt-Tab cover daily flow.
- SDDM greeter keyboard-layout switching is visual-only; layouts are set
  system-wide via Settings > Keyboard (localectl).
- Store screenshots/icons depend on Debian AppStream metadata; run
  "Check for updates" once after first boot if listings are empty.
- Secure Boot is on the roadmap (BIOS + standard UEFI work today).
- 32-bit (i386) is not supported: the modern Wayland GPU stack requires
  amd64. 2007-era 64-bit hardware is supported; see Safe Graphics entry.
