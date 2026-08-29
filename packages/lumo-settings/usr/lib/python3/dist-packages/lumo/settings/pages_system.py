"""Lumo Settings - system pages: displays, input, keyboard, users, about…"""
import os
import re

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from . import util  # noqa: E402
from .pages_core import refresh_async  # noqa: E402

run_out = util.run_out
run = util.run


# ============================== Displays ==============================
class DisplaysPage(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.append(util.page_title("Displays"))
        self.status = util.spinner_label("Reading display configuration…")
        self.append(self.status)
        self.out_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.append(self.out_box)
        refresh_async(self._probe, self._apply)

    def _probe(self):
        return run_out(["wlr-randr"])

    def _apply(self, data):
        text = data if isinstance(data, str) else ""
        if not text.strip():
            self.status.set_text("wlr-randr is unavailable (not a wlroots session?).")
            return False
        self.status.set_text("")
        outputs = []
        current = None
        for line in text.splitlines():
            if " enabled" in line or " disabled" in line:
                name = line.split()[0]
                current = {"name": name, "modes": []}
                outputs.append(current)
            elif current is not None and re.search(r"\d{3,}x\d{3,}", line):
                mm = re.search(r"(\d{3,5})x(\d{3,5})", line)
                if mm:
                    mode = f"{mm.group(1)}x{mm.group(2)}"
                    if mode not in current["modes"]:
                        current["modes"].append(mode)
        for out in outputs:
            combo = Gtk.DropDown()
            if out["modes"]:
                combo.set_model(Gtk.StringList.new(out["modes"]))
            apply_btn = util.button("Apply", flat=True)
            sel_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            sel_box.append(combo)
            sel_box.append(apply_btn)

            def do_apply(_b, combo=combo, name=out["name"]):
                sel = combo.get_selected_item()
                if sel:
                    run(["wlr-randr", "--output", name, "--mode", sel.get_string()])

            apply_btn.connect("clicked", do_apply)
            self.out_box.append(util.row(out["name"], "Resolution", sel_box))
        return False


# ============================== Mouse & Touchpad ==============================
class InputPage(Gtk.Box):
    RC = os.path.expanduser("~/.config/labwc/rc.xml")

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.append(util.page_title("Mouse & Touchpad"))
        self.natural = util.switch()
        self.natural.connect("state-set", self._on_natural)
        self.append(util.row("Natural scrolling",
                             "Touchpad scrolls like a phone screen", self.natural))
        self.tap = util.switch()
        self.tap.connect("state-set", self._on_tap)
        self.append(util.row("Tap to click", "Tap the touchpad to click", self.tap))
        self.status = util.spinner_label("Reading libinput settings…")
        self.append(self.status)
        refresh_async(self._probe, self._apply)

    def _probe(self):
        rc = self._load_xml()
        if rc is None:
            return None
        pad = rc.find("libinput/device[@category='touchpad']")
        natural = tap = False
        if pad is not None:
            ns = pad.find("naturalScroll")
            natural = ns is not None and ns.text == "yes"
            tp = pad.find("tap")
            tap = tp is not None and tp.text == "yes"
        return {"natural": natural, "tap": tap}

    def _load_xml(self):
        import xml.etree.ElementTree as ET
        path = self.RC
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            ok, _out, _err = run(["cp", "/etc/xdg/labwc/rc.xml", path])
            if not ok:
                return None
        try:
            return ET.parse(path)
        except Exception:
            return None

    def _apply(self, data):
        if data is None or isinstance(data, Exception):
            self.status.set_text("Could not read labwc configuration.")
            return False
        self.status.set_text("")
        self.natural.handler_block_by_func(self._on_natural)
        self.tap.handler_block_by_func(self._on_tap)
        self.natural.set_active(data["natural"])
        self.tap.set_active(data["tap"])
        self.natural.handler_unblock_by_func(self._on_natural)
        self.tap.handler_unblock_by_func(self._on_tap)
        return False

    def _save_toggle(self, tag, value):
        def apply():
            tree = self._load_xml()
            if tree is None:
                return
            root = tree.getroot()
            lib = root.find("libinput")
            if lib is None:
                from xml.etree.ElementTree import SubElement
                lib = SubElement(root, "libinput")
            pad = None
            for dev in lib.findall("device"):
                if dev.get("category") == "touchpad":
                    pad = dev
                    break
            if pad is None:
                from xml.etree.ElementTree import SubElement
                pad = SubElement(lib, "device")
                pad.set("category", "touchpad")
            el = pad.find(tag)
            if el is None:
                from xml.etree.ElementTree import SubElement
                el = SubElement(pad, tag)
            el.text = "yes" if value else "no"
            tree.write(self.RC, encoding="unicode", xml_declaration=True)
            run(["labwc-message", "reconfigure"])
        refresh_async(apply, lambda _r: None)

    def _on_natural(self, _sw, state):
        self._save_toggle("naturalScroll", state)
        return False

    def _on_tap(self, _sw, state):
        self._save_toggle("tap", state)
        return False


# ============================== Keyboard ==============================
class KeyboardPage(Gtk.Box):
    LAYOUTS = [
        ("English (US)", "us"), ("Arabic", "ar"),
        ("German", "de"), ("French", "fr"), ("Spanish", "es"), ("Italian", "it"),
        ("British", "gb"), ("Russian", "ru"), ("Turkish", "tr"),
    ]

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.append(util.page_title("Keyboard"))
        self.combo = Gtk.DropDown()
        self.append(util.row("Layout", "Applied at next login (system-wide)", self.combo))
        apply_btn = util.button("Apply layout")
        apply_btn.connect("clicked", self._apply_layout)
        self.append(util.row("Set system keyboard layout",
                             "Uses localectl; admin authorization may be asked",
                             apply_btn))
        self.status = util.spinner_label("Reading current layout…")
        self.append(self.status)
        self.refresh()

    def refresh(self):
        def probe():
            return run_out(["bash", "-c",
                "grep -E '^XKBLAYOUT' /etc/default/keyboard | cut -d\\\" -f2"])
        refresh_async(probe, self._apply)

    def _apply(self, data):
        current = (data or "us").strip() or "us"
        names = [n for n, _c in self.LAYOUTS]
        codes = [c for _n, c in self.LAYOUTS]
        # de-duplicate keeping order
        seen = set()
        uniq = [(n, c) for n, c in self.LAYOUTS if not (c in seen or seen.add(c))]
        self._codes = [c for _n, c in uniq]
        self.combo.set_model(Gtk.StringList.new([n for n, _c in uniq]))
        if current in self._codes:
            self.combo.set_selected(self._codes.index(current))
        self.status.set_text(f"Current layout: {current}")
        return False

    def _apply_layout(self, _btn):
        idx = self.combo.get_selected()
        if 0 <= idx < len(self._codes):
            code = self._codes[idx]
            def apply():
                return run(["localectl", "set-x11-keymap", code])
            def done(result):
                ok, _o, err = result
                self.status.set_text("Layout set - sign out and back in to apply."
                                     if ok else f"Failed: {err.strip() or 'not authorized'}")
            refresh_async(apply, done)


# ============================== Printers ==============================
class PrintersPage(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.append(util.page_title("Printers"))
        manage = util.button("Manage printers")
        manage.connect("clicked", lambda *_: run(["system-config-printer"]))
        self.append(util.row("Printing", "CUPS print server and configuration",
                             manage))
        self.status = util.spinner_label("Checking CUPS…")
        self.append(self.status)
        refresh_async(self._probe, self._apply)

    def _probe(self):
        ok, out, _err = util.run(["bash", "-c", "lpstat -p 2>/dev/null | head -n 10"])
        return {"running": ok, "printers": out}

    def _apply(self, data):
        if isinstance(data, Exception):
            self.status.set_text("CUPS is not installed.")
            return False
        printers = (data["printers"] or "").strip()
        if printers:
            self.status.set_text(printers)
        else:
            self.status.set_text("CUPS is running; no printers configured yet.")
        return False


# ============================== Region & Language ==============================
class RegionPage(Gtk.Box):
    LOCALES = [
        ("English (US)", "en_US.UTF-8"),
        ("Arabic (Egypt)", "ar_EG.UTF-8"),
        ("Arabic (Saudi Arabia)", "ar_SA.UTF-8"),
        ("German", "de_DE.UTF-8"),
        ("French", "fr_FR.UTF-8"),
        ("Spanish", "es_ES.UTF-8"),
    ]

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.append(util.page_title("Region & Language"))
        self.combo = Gtk.DropDown()
        self.append(util.row("Language", "Interface language and formats; RTL languages "
                                               "such as Arabic mirror the UI automatically. "
                                               "Takes effect at next login.",
                             self.combo))
        apply_btn = util.button("Apply language")
        apply_btn.connect("clicked", self._apply_locale)
        self.append(util.row("Set system locale", "Uses localectl", apply_btn))
        self.status = util.spinner_label("Reading current locale…")
        self.append(self.status)

        def probe():
            return run_out(["bash", "-c", "locale | grep ^LANG= | cut -d= -f2"])
        refresh_async(probe, self._apply)

    def _apply(self, data):
        current = (data or "en_US.UTF-8").strip() or "en_US.UTF-8"
        uniq = list(dict.fromkeys(self.LOCALES))
        self._codes = [c for _n, c in uniq]
        self.combo.set_model(Gtk.StringList.new([n for n, _c in uniq]))
        if current in self._codes:
            self.combo.set_selected(self._codes.index(current))
        self.status.set_text(f"Current locale: {current}")
        return False

    def _apply_locale(self, _btn):
        idx = self.combo.get_selected()
        if 0 <= idx < len(self._codes):
            code = self._codes[idx]
            def apply():
                return run(["localectl", "set-locale", f"LANG={code}"])
            def done(result):
                ok, _o, err = result
                self.status.set_text("Locale set - sign out and back in to apply."
                                     if ok else f"Failed: {err.strip() or 'not authorized'}")
            refresh_async(apply, done)


# ============================== Accessibility ==============================
class A11yPage(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.append(util.page_title("Accessibility"))

        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.75, 1.75, 0.05)
        scale.set_size_request(260, -1)
        self.scale_row = util.row("Text size", "Interface text scaling", scale)
        self.append(self.scale_row)

        anim = util.switch()
        anim.connect("state-set", self._on_anim)
        self.append(util.row("Animations", "Window and interface animations", anim))

        cursor = Gtk.DropDown()
        cursor.set_model(Gtk.StringList.new(["Default (24)", "Large (32)", "Extra large (48)"]))
        cursor.connect("notify::selected-item", self._on_cursor)
        self.append(util.row("Cursor size", None, cursor))

        def probe():
            try:
                out = util.run_out(["gsettings", "get", "org.gnome.desktop.interface",
                                    "text-scaling-factor"]).strip()
                factor = float(out)
            except Exception:
                factor = 1.0
            anims = util.run_out(["gsettings", "get", "org.gnome.desktop.interface",
                                  "enable-animations"]).strip()
            return {"factor": factor, "anims": anims == "true"}

        def apply(data):
            scale.set_value(data["factor"])
            anim.handler_block_by_func(self._on_anim)
            anim.set_active(data["anims"])
            anim.handler_unblock_by_func(self._on_anim)
            return False

        scale.connect("value-changed", self._on_scale)
        refresh_async(probe, apply)

    def _on_scale(self, scale):
        run(["gsettings", "set", "org.gnome.desktop.interface",
             "text-scaling-factor", str(round(scale.get_value(), 2))])

    def _on_anim(self, _sw, state):
        run(["gsettings", "set", "org.gnome.desktop.interface",
             "enable-animations", "true" if state else "false"])
        return False

    def _on_cursor(self, combo, _pspec):
        sizes = [24, 32, 48]
        idx = combo.get_selected()
        if 0 <= idx < len(sizes):
            run(["gsettings", "set", "org.gnome.desktop.interface",
                 "cursor-size", str(sizes[idx])])


# ============================== Users ==============================
class UsersPage(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.append(util.page_title("Users"))
        self.info = util.spinner_label("Loading account…")
        self.append(self.info)
        passwd_btn = util.button("Change password")
        passwd_btn.connect("clicked", lambda *_: run(
            ["foot", "-e", "bash", "-lc", "passwd; read -n1 -p 'Done - press any key'"]))
        self.append(util.row("Password", "Change your login password", passwd_btn))
        refresh_async(self._probe, self._apply)

    def _probe(self):
        user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
        full = run_out(["bash", "-c", f"getent passwd {user} | cut -d: -f5 | cut -d, -f1"])
        groups = run_out(["bash", "-c", f"id -Gn {user}"])
        return {"user": user, "full": full.strip() or user, "groups": groups.strip()}

    def _apply(self, data):
        if isinstance(data, Exception) or not data["user"]:
            self.info.set_text("Could not determine current user.")
            return False
        self.info.set_text(
            f"{data['full']} ({data['user']}) - groups: {data['groups']}")
        return False


# ============================== Date & Time ==============================
class DateTimePage(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.append(util.page_title("Date & Time"))
        self.ntp = util.switch()
        self.ntp.connect("state-set", self._on_ntp)
        self.append(util.row("Automatic date & time",
                             "Requires internet time (NTP)", self.ntp))
        self.tz_combo = Gtk.DropDown()
        set_tz = util.button("Set timezone")
        set_tz.connect("clicked", self._set_tz)
        self.append(util.row("Timezone", "Pick from common zones or type below", self.tz_combo))
        self.append(util.row("Apply", None, set_tz))
        self.status = util.spinner_label("Reading timedatectl…")
        self.append(self.status)
        refresh_async(self._probe, self._apply)

    def _probe(self):
        info = run_out(["timedatectl"])
        ntp = "NTP service: active" in info
        tz = ""
        for line in info.splitlines():
            if "Time zone:" in line:
                tz = line.split(":", 1)[1].strip().split(" ")[0]
        zones = run_out(["bash", "-c",
            "timedatectl list-timezones | grep -E 'Africa/(Lagos|Cairo|Nairobi)|Europe/(London|Paris|Berlin|Istanbul|Moscow)|Asia/(Dubai|Riyadh|Tehran|Karachi|Tokyo)|America/(New_York|Los_Angeles|Sao_Paulo)|Australia/Sydney' | head -n 30"])
        return {"ntp": ntp, "tz": tz, "zones": zones}

    def _apply(self, data):
        if isinstance(data, Exception):
            self.status.set_text("timedatectl unavailable.")
            return False
        self.ntp.handler_block_by_func(self._on_ntp)
        self.ntp.set_active(data["ntp"])
        self.ntp.handler_unblock_by_func(self._on_ntp)
        zones = [z for z in (data["zones"] or "").splitlines() if z.strip()]
        if data["tz"] and data["tz"] not in zones:
            zones.insert(0, data["tz"])
        self._zones = zones
        if zones:
            self.tz_combo.set_model(Gtk.StringList.new(zones))
            if data["tz"] in zones:
                self.tz_combo.set_selected(zones.index(data["tz"]))
        self.status.set_text(f"Current timezone: {data['tz'] or 'unknown'}")
        return False

    def _on_ntp(self, _sw, state):
        run(["timedatectl", "set-ntp", "true" if state else "false"])
        return False

    def _set_tz(self, _btn):
        item = self.tz_combo.get_selected_item()
        if not item:
            return
        def apply():
            return run(["timedatectl", "set-timezone", item.get_string()])
        def done(result):
            ok, _o, err = result
            self.status.set_text("Timezone updated." if ok
                                 else f"Failed: {err.strip() or 'not authorized'}")
        refresh_async(apply, done)


# ============================== Default Applications ==============================
class DefaultsPage(Gtk.Box):
    GROUPS = [
        ("Web browser", "x-scheme-handler/http",
         ["firefox-esr.desktop", "chromium.desktop", "epiphany.desktop"]),
        ("File manager", "inode/directory",
         ["org.gnome.Nautilus.desktop", "nemo.desktop", "pcmanfm.desktop"]),
        ("Text editor", "text/plain",
         ["org.gnome.TextEditor.desktop", "gedit.desktop", "org.xfce.mousepad.desktop"]),
        ("Image viewer", "image/png",
         ["org.gnome.Loupe.desktop", "eog.desktop", "gthumb.desktop"]),
        ("Video player", "video/mp4",
         ["mpv.desktop", "org.gnome.Totem.desktop", "vlc.desktop"]),
    ]

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.append(util.page_title("Default Applications"))
        self.combos = {}
        for label, mime, candidates in self.GROUPS:
            combo = Gtk.DropDown()
            self.combos[mime] = (combo, candidates)
            self.append(util.row(label, mime, combo))
        apply = util.button("Set defaults")
        apply.connect("clicked", self._apply_defaults)
        self.append(util.row("Apply", "Writes your personal mimeapps.list", apply))
        refresh_async(self._probe, self._apply)

    def _probe(self):
        result = {}
        for _label, mime, candidates in self.GROUPS:
            ok, out, _e = util.run(["xdg-mime", "query", "default", mime])
            result[mime] = out.strip() if ok and out.strip() else ""
        return result

    def _apply(self, data):
        for mime, (combo, candidates) in self.combos.items():
            current = data.get(mime, "")
            cand = list(candidates)
            if current and current not in cand:
                cand.insert(0, current)
            combo.set_model(Gtk.StringList.new(cand))
            if current in cand:
                combo.set_selected(cand.index(current))
        return False

    def _apply_defaults(self, _btn):
        def apply():
            for mime, (combo, _c) in self.combos.items():
                item = combo.get_selected_item()
                if item:
                    run(["xdg-mime", "default", item.get_string(), mime])
            return True
        refresh_async(apply, lambda _r: None)


# ============================== About ==============================
class AboutPage(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14,
                        halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        logo = Gtk.Image.new_from_file(
            "/usr/share/icons/hicolor/scalable/apps/lumo-logo.svg")
        logo.set_pixel_size(96)
        self.append(logo)
        title = Gtk.Label(label="Lumo OS 1.0 (Aurora)")
        title.add_css_class("lumo-title")
        self.append(title)
        sub = Gtk.Label(label="Featherlight. Fearless. Beautiful. - Debian 13 base")
        sub.add_css_class("lumo-subtitle")
        self.append(sub)

        self.info = util.spinner_label("Gathering system information…")
        self.info.set_justify(Gtk.Justification.CENTER)
        self.append(self.info)

        refresh_async(self._probe, self._apply)

    def _probe(self):
        cpu = util.run_out(["bash", "-c",
            "lscpu | grep 'Model name' | sed 's/.*: *//' | head -n1"])
        mem = util.run_out(["bash", "-c",
            "free -h | awk '/Mem:/ {print $2}'"])
        disk = util.run_out(["bash", "-c",
            "df -h / | awk 'NR==2 {print $3 \" used of \" $2}'"])
        gpu = util.run_out(["bash", "-c",
            "lspci | grep -iE 'vga|3d' | head -n1 | sed 's/.*: //'"])
        host = util.run_out(["hostnamectl", "--static"])
        return {"cpu": cpu.strip(), "mem": mem.strip(), "disk": disk.strip(),
                "gpu": gpu.strip(), "host": host.strip()}

    def _apply(self, data):
        if isinstance(data, Exception):
            self.info.set_text("System information unavailable.")
            return False
        self.info.set_text(
            f"Hostname: {data['host']}\n"
            f"CPU: {data['cpu']}\n"
            f"Memory: {data['mem']}\n"
            f"Graphics: {data['gpu']}\n"
            f"Disk: {data['disk']}")
        return False
