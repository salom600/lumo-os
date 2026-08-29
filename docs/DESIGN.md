# Design System - Lumo OS "Aurora"

Reference: `docs/img/design-reference.png` (uploaded UI design - mandatory).

## Extracted tokens

| Token | Value |
|---|---|
| Accent | `#3584e4` (blue), 8 selectable accents |
| Top bar | `rgba(10,11,18,0.84)`, 38 px, centered clock, status icons right |
| Dock | floating left, `rgba(18,20,30,0.74)`, radius 24, width 62 |
| Window surfaces | `rgba(21,23,34,0.94)` glass, radius 16-18, hairline `rgba(255,255,255,0.09)` border |
| Cards/rows | `rgba(255,255,255,0.055)`, radius 14 |
| Selected pill | accent @ 28% opacity |
| Text | `#f2f1f0` primary, 62% opacity secondary |
| Light mode | `rgba(250,250,253,0.95)` surfaces, white cards, same accent |
| Fonts | Inter (UI), Noto Sans + Noto Sans Arabic (coverage/RTL), Noto Sans Mono (terminal) |
| Icons | Papirus (matches the blue folders in the reference) |
| Wallpaper | purple/blue fluid "aurora mountains" (generated to match reference) |
| Corners | windows 12-16 px, cards 14 px, dock 24 px, tiles/pills 12-14 px |

## Component mapping (design -> implementation)

| Design element | Implementation |
|---|---|
| Top bar "Activities" | waybar custom module -> `lumo-launcher` overlay |
| Centered clock "Tue Oct 24 10:42 AM" | waybar clock module `{:%a %b %-d %I:%M %p}` -> `lumo-calendar` |
| WiFi/BT/battery%/volume/power cluster | waybar network/bluetooth/battery/pulseaudio/image modules -> `lumo-qs` / `lumo-power` |
| Floating left dock with colored app icons | waybar dock bar (image modules, Papirus icons) + live taskbar + trash |
| Settings sidebar with selected blue pill | Lumo Settings ListBox with `.lumo-sidebar row:selected` styling |
| Appearance: Light/Dark style cards | Lumo Settings > Appearance (ToggleButtons with preview tiles) |
| Nautilus-style file manager | Nautilus (dark mode via gsettings), sidebar Favorites/System matches reference |
| Rounded translucent windows | GTK CSD + labwc `corner_radius 12` for SSD windows + our apps CSS |
| Purple/blue aurora wallpaper | `lumo-aurora-dark.png` / light variant, wired to swaybg + gsettings |

## Modes

- Dark (default) / Light - switches: gsettings color-scheme, GTK3/4 ini files,
  Lumo app CSS file, wallpaper variant. One command: `/usr/bin/lumo-appearance dark|light`.
- Accent: 8 GNOME-palette choices stored in `~/.config/lumo/appearance.json`,
  consumed by Lumo apps via `lumo.style`; Adwaita apps follow via
  `org.gnome.desktop.interface accent-color` when supported.
