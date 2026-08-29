# Lumo OS - Architecture

## Stack decisions (and why)

| Layer | Choice | Why |
|---|---|---|
| Base | Debian 13 trixie, mmdebstrap | cleanest minimal base, reproducible, no heavy spin ancestry |
| Compositor | labwc (wlroots) | ~15 MB RAM, floating window manager, rounded corners, Wayland-native, XWayland for games |
| Shell chrome | Waybar (bar + dock) | mature, CSS-themable, SNI tray + wlr/taskbar; single process hosts both bars |
| Shell tools | Python 3 + GTK4 + gtk4-layer-shell | fast to maintain, light enough (tools exit when closed), full layer-shell for overlays |
| Login | SDDM + custom QML theme | real greeter API (auth, sessions, power), X11 greeter works on ancient GPUs |
| Installer | Calamares | UEFI+BIOS, squashfs copy (unpackfs), full branding |
| Audio/video | PipeWire + WirePlumber | modern, low overhead |
| Network | NetworkManager driven via nmcli | no applet needed; QS + Settings control it directly |
| Notifications | mako | tiny, themed |
| Apps | Nautilus, Foot, Firefox ESR, GNOME Text Editor, Loupe, mpv, File Roller | GTK4/modern, consistent identity |
| Gaming | Mesa + Vulkan, XWayland, GameMode, lumo-perf governor toggle, store sections | give games the resources |
| Low RAM | zram(zstd), sysctl tuning, volatile-capped journald, no idle daemons | targets <150 MB idle |

## Boot flow

1. GRUB (BIOS+UEFI, themed) -> kernel + initrd from ISO `/live/`
2. live-boot mounts squashfs, tmpfs overlay
3. `lumo-live-setup.service` (live only, guarded by `ConditionPathExists=/run/live/medium`):
   creates user `lumo` (sudo), enables SDDM autologin into the Lumo session,
   and (only with `lumo.test=1`) installs the ephemeral SSH key from the kernel cmdline.
4. SDDM starts the greeter (X11) or autologins into `lumo-session`
5. `lumo-session` exports the session env (XKB from `/etc/default/keyboard` for Arabic/RTL)
   and execs **labwc**
6. labwc autostart runs: waybar (bar+dock), mako, mate-polkit, swayidle, wallpaper service

## Installed system flow

Calamares copies the pristine squashfs (`unpackfs`), sets up locale/keyboard/users/GRUB,
then `shellprocess-lumo-finalize` purges calamares + live packages and removes the live
sudoers/autologin files. Result: a clean installed Lumo OS.

## RAM budget (idle session)

| Component | approx RSS |
|---|---|
| labwc | ~15 MB |
| waybar (bar + dock) | ~45 MB |
| mako | ~8 MB |
| swaybg | ~4 MB |
| swayidle | ~3 MB |
| mate-polkit | ~15 MB |
| PipeWire + WirePlumber | ~20 MB |
| NetworkManager | ~15 MB |
| misc (dbus, gvfs udiskd on demand) | ~15 MB |
| **Total (incl. system daemons)** | **~120-140 MB** |

Reported honestly by CI on every build; shell-only (compositor+bar+tools) is well under 100 MB.

## Test mode (CI)

- kernel cmdline `lumo.test=1 lumo.pubkey=<base64>` -> sshd + ephemeral key + autologin
- CI: extract kernel/initrd, QEMU (TCG), wait SSH, collect `free`/vmstat/`systemctl --failed`/`systemd-analyze`,
  capture grim screenshots of every shell surface, validate with PIL, write `validation-report.md`
