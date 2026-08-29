"""Shared GTK styling and palette helpers for Lumo OS applications.

All Lumo apps import this to apply the current Lumo theme (dark/light +
accent color) consistently. The active mode and accent are stored in a tiny
state file written by Lumo Settings; gsettings drives Adwaita apps in
parallel so both worlds stay in sync.
"""
import json
import os

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gio, Gtk  # noqa: E402

THEME_DIR = "/usr/share/lumo/theme"
STATE_FILE = os.path.expanduser("~/.config/lumo/appearance.json")

ACCENTS = {
    "blue": "#3584e4",
    "teal": "#2190a4",
    "green": "#3a944a",
    "yellow": "#c88800",
    "orange": "#ed5b00",
    "red": "#e62d42",
    "purple": "#9141ac",
    "pink": "#e562a4",
}

_dark = None
_accent = None


def is_dark():
    """Current dark-mode preference (default True)."""
    global _dark
    if _dark is None:
        val = None
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as fh:
                val = json.load(fh).get("dark")
        except Exception:
            val = None
        if val is None:
            try:
                sett = Gio.Settings.new("org.gnome.desktop.interface")
                val = sett.get_string("color-scheme") != "default"
            except Exception:
                val = True
        _dark = bool(val)
    return _dark


def accent_color():
    """Current accent hex color (default blue)."""
    global _accent
    if _accent is None:
        name = None
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as fh:
                name = json.load(fh).get("accent")
        except Exception:
            name = None
        if name not in ACCENTS:
            name = "blue"
        _accent = ACCENTS[name]
    return _accent


def css_path():
    return os.path.join(THEME_DIR, "apps-light.css" if not is_dark() else "apps-dark.css")


def apply_to_display(light=None):
    """Attach the Lumo theme CSS provider to the default display."""
    provider = Gtk.CssProvider()
    path = css_path() if light is None else (
        os.path.join(THEME_DIR, "apps-light.css") if light else os.path.join(THEME_DIR, "apps-dark.css"))
    try:
        provider.load_from_file(Gio.File.new_for_path(path))
        disp = Gdk.Display.get_default()
        if disp:
            Gtk.StyleContext.add_provider_for_display(
                disp, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 10)
        return True
    except Exception as exc:  # theme is cosmetic; never crash the app
        print(f"[lumo] theme load failed: {exc}")
        return False


def tune_switch(switch):
    """Keep default switch styling but let CSS target it."""
    switch.add_css_class("lumo-switch")
    return switch


def state_file_path():
    return STATE_FILE
