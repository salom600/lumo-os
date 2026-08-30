#!/bin/sh
# Lumo wallpaper resolver/daemon.
# Priority: user override (~/.config/lumo/wallpaper) -> light/dark default
# by current appearance. Restarted by Lumo Settings on changes.
USER_WP="$HOME/.config/lumo/wallpaper"
STATE="$HOME/.config/lumo/appearance.json"

if [ -s "$USER_WP" ]; then
    WP="$(head -n1 "$USER_WP")"
else
    DARK=yes
    if [ -r "$STATE" ]; then
        if grep -q '"dark"[[:space:]]*:[[:space:]]*false' "$STATE" 2>/dev/null; then
            DARK=no
        fi
    else
        # fall back to gsettings (source of truth for Adwaita apps)
        if command -v gsettings >/dev/null 2>&1; then
            SCHEME="$(gsettings get org.gnome.desktop.interface color-scheme 2>/dev/null || echo 'prefer-dark')"
            [ "$SCHEME" = "'default'" ] && DARK=no
        fi
    fi
    if [ "$DARK" = yes ]; then
        WP=/usr/share/lumo/wallpapers/lumo-aurora-dark.png
    else
        WP=/usr/share/lumo/wallpapers/lumo-aurora-light.png
    fi
fi

[ -r "$WP" ] || WP=/usr/share/lumo/wallpapers/lumo-aurora-dark.png

# update GNOME keys so portals/lock screen follow along
if command -v gsettings >/dev/null 2>&1; then
    gsettings set org.gnome.desktop.background picture-uri "$WP" 2>/dev/null || true
    gsettings set org.gnome.desktop.background picture-uri-dark "$WP" 2>/dev/null || true
    gsettings set org.gnome.desktop.screensaver picture-uri "$WP" 2>/dev/null || true
fi

exec swaybg -m fill -i "$WP"
