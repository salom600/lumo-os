"""Lumo Settings - connectivity & personalization pages (real backends)."""
import json
import os

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from . import util  # noqa: E402

run_out = util.run_out
run = util.run


def refresh_async(fn, done):
    """Run fn in a thread; pass its result to done(result) on the UI thread."""
    def worker():
        try:
            result = fn()
        except Exception as exc:
            result = exc
        GLib.idle_add(done, result)
    threading.Thread(target=worker, daemon=True).start()


# ============================== Wi-Fi ==============================
class WifiPage(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.append(util.page_title("Wi-Fi"))
        self.status = util.spinner_label("Checking Wi-Fi…")
        self.append(self.status)
        self.wifi_switch = util.switch()
        sw_row = util.row("Wi-Fi", "Enable or disable wireless radio", self.wifi_switch)
        self.append(sw_row)
        self.networks_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.append(self.networks_box)
        self.wifi_switch.connect("state-set", self._on_toggle)
        refresh_async(self._probe, self._apply_probe)

    def _probe(self):
        on = run_out(["nmcli", "radio", "wifi"]).strip().lower() == "enabled"
        if not on:
            return {"on": False, "networks": [], "current": ""}
        networks = run_out(["bash", "-c",
            "nmcli -t -f IN-USE,SSID,SIGNAL,SECURITY dev wifi list 2>/dev/null | sort -t: -k3 -rn | head -n 20"])
        current = run_out(["bash", "-c",
            "nmcli -t -f NAME,TYPE,DEVICE connection show --active | grep wireless | cut -d: -f1 | head -n1"]).strip()
        return {"on": True, "networks": networks, "current": current}

    def _apply_probe(self, data):
        if isinstance(data, Exception) or data is None:
            self.status.set_text("NetworkManager is not available.")
            return False
        self.wifi_switch.handler_block_by_func(self._on_toggle)
        self.wifi_switch.set_active(data["on"])
        self.wifi_switch.handler_unblock_by_func(self._on_toggle)
        while self.networks_box.get_first_child():
            self.networks_box.remove(self.networks_box.get_first_child())
        if not data["on"]:
            self.status.set_text("Wi-Fi radio is off.")
            return False
        cur = data["current"]
        self.status.set_text(f"Connected to {cur}" if cur else "Not connected")
        seen = set()
        for line in (data["networks"] or "").splitlines():
            parts = line.split(":")
            if len(parts) < 4 or not parts[1]:
                continue
            in_use, ssid, signal, security = parts[0], parts[1], parts[2], parts[3]
            if ssid in seen:
                continue
            seen.add(ssid)
            secure = security not in ("", "--")
            label = f"{ssid}  ({signal}%)" + ("  \U0001f512" if secure else "")
            btn = util.button("Connect" if ssid != cur else "Disconnect", flat=True)
            btn.connect("clicked", self._connect_flow, ssid, secure, ssid == cur)
            self.networks_box.append(util.row(label, None, btn))
        if not seen:
            self.status.set_text("No networks found.")
        return False

    def _on_toggle(self, _sw, state):
        def apply():
            run(["nmcli", "radio", "wifi", "on" if state else "off"])
        def done(_r):
            refresh_async(self._probe, self._apply_probe)
        refresh_async(apply, done)
        return False

    def _connect_flow(self, _btn, ssid, secure, disconnect):
        if disconnect:
            refresh_async(lambda: run(["nmcli", "connection", "down", ssid]), 
                          lambda _r: refresh_async(self._probe, self._apply_probe))
            return
        if not secure:
            refresh_async(lambda: run(["nmcli", "dev", "wifi", "connect", ssid]),
                          self._connect_done)
            return
        dialog = Gtk.Dialog(title=f"Connect to {ssid}", modal=True)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Connect", Gtk.ResponseType.OK)
        dialog.set_default_size(380, 140)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(14); box.set_margin_bottom(14)
        box.set_margin_start(16); box.set_margin_end(16)
        lab = Gtk.Label(label=f"Password for {ssid}:", halign=Gtk.Align.START)
        box.append(lab)
        entry = Gtk.PasswordEntry()
        entry.add_css_class("lumo-entry")
        entry.set_show_peek_icon(True)
        box.append(entry)
        dialog.get_content_area().append(box)
        dialog.connect("response", self._password_response, entry, ssid)
        dialog.present()

    def _password_response(self, dialog, resp, entry, ssid):
        if resp == Gtk.ResponseType.OK:
            pw = entry.get_text()
            refresh_async(lambda: run(["nmcli", "dev", "wifi", "connect", ssid,
                                       "password", pw]),
                          self._connect_done)
        dialog.destroy()

    def _connect_done(self, result):
        ok, out, err = result if isinstance(result, tuple) else (False, "", "")
        if not ok:
            self.status.set_text("Connection failed. Check the password and try again.")
        refresh_async(self._probe, self._apply_probe)
        return False


# ============================== Bluetooth ==============================
class BluetoothPage(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.append(util.page_title("Bluetooth"))
        self.status = util.spinner_label("Checking adapter…")
        self.append(self.status)
        self.bt_switch = util.switch()
        self.append(util.row("Bluetooth", "Power the adapter on or off", self.bt_switch))
        self.devices_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.append(self.devices_box)
        self.bt_switch.connect("state-set", self._on_toggle)
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        scan = util.button("Scan for devices", flat=True)
        scan.connect("clicked", lambda *_: refresh_async(self._scan, self._apply))
        actions.append(scan)
        self.append(actions)
        refresh_async(self._probe, self._apply)

    def _probe(self):
        out = run_out(["bluetoothctl", "show"])
        powered = "Powered: yes" in out
        devices = ""
        if powered:
            run_out(["bash", "-c", "bluetoothctl scan off 2>/dev/null"])
            devices = run_out(["bluetoothctl", "devices", "Paired"])
        return {"powered": powered, "devices": devices}

    def _apply(self, data):
        if isinstance(data, Exception):
            self.status.set_text("Bluetooth unavailable (bluez not running?).")
            return False
        self.bt_switch.handler_block_by_func(self._on_toggle)
        self.bt_switch.set_active(data["powered"])
        self.bt_switch.handler_unblock_by_func(self._on_toggle)
        self.status.set_text("Adapter powered" if data["powered"] else "Adapter off")
        while self.devices_box.get_first_child():
            self.devices_box.remove(self.devices_box.get_first_child())
        for line in (data["devices"] or "").splitlines():
            parts = line.split(" ", 2)
            if len(parts) < 3:
                continue
            _dev, mac, name = parts
            btn = util.button("Disconnect", flat=True)
            btn.connect("clicked", self._device_cmd, mac, "disconnect")
            rm = util.button("Remove", flat=True)
            rm.connect("clicked", self._device_cmd, mac, "remove")
            actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            actions.append(btn)
            actions.append(rm)
            self.devices_box.append(util.row(name, mac, actions))
        if data["powered"] and not (data["devices"] or "").strip():
            self.devices_box.append(util.spinner_label("No paired devices yet."))
        return False

    def _on_toggle(self, _sw, state):
        def apply():
            cmd = "power on" if state else "power off"
            run(["bluetoothctl"] + cmd.split())
        refresh_async(apply, lambda _r: refresh_async(self._probe, self._apply))
        return False

    def _scan(self):
        run_out(["bash", "-c", "timeout 8 bluetoothctl scan on >/dev/null 2>&1; true"])
        return run_out(["bluetoothctl", "devices"])

    def _device_cmd(self, _btn, mac, cmd):
        def apply():
            run(["bluetoothctl", cmd, mac])
        refresh_async(apply, lambda _r: refresh_async(self._probe, self._apply))


# ============================== Network ==============================
class NetworkPage(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.append(util.page_title("Network"))
        self.devices_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.append(self.devices_box)
        self.status = util.spinner_label("Reading device state…")
        self.append(self.status)
        refresh_async(self._probe, self._apply)

    def _probe(self):
        devices = run_out(["bash", "-c",
            "nmcli -t -f DEVICE,TYPE,STATE,CONNECTION dev status"])
        conn = run_out(["nmcli", "-t", "-f", "ADDRESS,GATEWAY,DNS", "dev", "show"])
        vpn = run_out(["bash", "-c",
            "nmcli -t -f NAME,TYPE connection show --active | grep vpn"])
        return {"devices": devices, "conn": conn, "vpn": vpn}

    def _apply(self, data):
        if isinstance(data, Exception):
            self.status.set_text("NetworkManager unavailable.")
            return False
        while self.devices_box.get_first_child():
            self.devices_box.remove(self.devices_box.get_first_child())
        ip = ""
        for line in (data["conn"] or "").splitlines():
            if line.startswith("ADDRESS:"):
                ip = line.split(":", 1)[1].strip()
                break
        n = 0
        for line in (data["devices"] or "").splitlines():
            parts = line.split(":")
            if len(parts) < 4 or parts[1] == "loopback":
                continue
            n += 1
            self.devices_box.append(util.row(
                parts[3] or parts[0],
                f"{parts[0]} · {parts[1]} · {parts[2]}" + (f" · IP {ip}" if ip else "")))
        if not n:
            self.status.set_text("No network devices found.")
        else:
            self.status.set_text("")
        vpn = (data["vpn"] or "").strip()
        if vpn:
            self.append(util.row("VPN", vpn))
        return False


# ============================== Appearance ==============================
ACCENTS = [
    ("Blue", "#3584e4"), ("Teal", "#2190a4"), ("Green", "#3a944a"),
    ("Yellow", "#c88800"), ("Orange", "#ed5b00"), ("Red", "#e62d42"),
    ("Purple", "#9141ac"), ("Pink", "#e562a4"),
]


class AppearancePage(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.append(util.page_title("Appearance"))

        style_card = util.card()
        style_lab = Gtk.Label(label="Style", halign=Gtk.Align.START)
        style_lab.add_css_class("lumo-heading")
        style_card.append(style_lab)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14, homogeneous=True)
        self.dark_btn = Gtk.ToggleButton()
        self.light_btn = Gtk.ToggleButton()
        for btn, name, css_bg, css_fg in (
            (self.light_btn, "Light", "#f6f5f4", "#1d1d20"),
            (self.dark_btn, "Dark", "#1a1c2a", "#f2f1f0"),
        ):
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            preview = Gtk.Box()
            preview.set_size_request(170, 92)
            preview.add_css_class("lumo-preview")
            preview.set_margin_top(8)
            inner.append(preview)
            lab = Gtk.Label(label=name)
            inner.append(lab)
            btn.set_child(inner)
            row.append(btn)
        self.dark_btn.connect("toggled", self._set_mode, "dark")
        self.light_btn.connect("toggled", self._set_mode, "light")
        style_card.append(row)
        self.append(style_card)

        accent_card = util.card()
        accent_lab = Gtk.Label(label="Accent color", halign=Gtk.Align.START)
        accent_lab.add_css_class("lumo-heading")
        accent_card.append(accent_lab)
        swatches = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.accent_group = None
        for name, hexc in ACCENTS:
            b = Gtk.ToggleButton()
            b.set_size_request(34, 34)
            b.set_tooltip_text(name)
            b.add_css_class("lumo-swatch")
            css = Gtk.CssProvider()
            from gi.repository import Gio as _Gio
            css.load_from_data(f"button.lumo-swatch.accent-{name.lower()} {{ background: {hexc}; }}".encode())
            display = self.get_display()
            if display:
                from gi.repository import Gtk as _Gtk
                _Gtk.StyleContext.add_provider_for_display(display, css, 800)
            b.add_css_class(f"accent-{name.lower()}")
            b.connect("toggled", self._set_accent, name.lower())
            swatches.append(b)
            if name.lower() == "blue":
                b.set_active(True)
        accent_card.append(swatches)
        self.append(accent_card)

        self._sync_mode()
        self._sync_accent()

    def _sync_mode(self):
        from lumo import style as lumo_style
        dark = lumo_style.is_dark()
        self.dark_btn.handler_block_by_func(self._set_mode)
        self.light_btn.handler_block_by_func(self._set_mode)
        self.dark_btn.set_active(dark)
        self.light_btn.set_active(not dark)
        self.dark_btn.handler_unblock_by_func(self._set_mode)
        self.light_btn.handler_unblock_by_func(self._set_mode)

    def _set_mode(self, _btn, mode):
        if not _btn.get_active():
            return
        run(["/usr/bin/lumo-appearance", mode])

    def _sync_accent(self):
        pass

    def _set_accent(self, btn, name):
        if not btn.get_active():
            return
        cfg = os.path.expanduser("~/.config/lumo")
        os.makedirs(cfg, exist_ok=True)
        path = os.path.join(cfg, "appearance.json")
        data = {"dark": True, "accent": name}
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            pass
        data["accent"] = name
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        # wallpaper stays, but the shell may want to know; restart wallpaper daemon
        run(["systemctl", "--user", "restart", "lumo-wallpaper.service"])

    def swatches_iter(self):
        return []


# ============================== Background ==============================
class BackgroundPage(Gtk.Box):
    WALLPAPERS = [
        ("Aurora (dark)", "/usr/share/lumo/wallpapers/lumo-aurora-dark.png"),
        ("Aurora (light)", "/usr/share/lumo/wallpapers/lumo-aurora-light.png"),
    ]

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.append(util.page_title("Background"))
        grid = Gtk.FlowBox(max_children_per_line=3, min_children_per_line=2,
                           column_spacing=12, row_spacing=12)
        for name, path in self.WALLPAPERS:
            if not os.path.exists(path):
                continue
            cell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            thumb = Gtk.Picture.new_for_filename(path)
            thumb.set_size_request(240, 135)
            thumb.add_css_class("lumo-card")
            cell.append(thumb)
            lab = Gtk.Label(label=name)
            lab.add_css_class("lumo-dim")
            cell.append(lab)
            btn = Gtk.Button()
            btn.set_child(cell)
            btn.set_has_frame(False)
            btn.connect("clicked", self._set, path)
            grid.append(btn)

        custom = util.button("Choose custom image…", flat=True)
        custom.connect("clicked", self._choose)
        self.append(grid)
        self.append(custom)

    def _set(self, _btn, path):
        def apply():
            cfg = os.path.expanduser("~/.config/lumo")
            os.makedirs(cfg, exist_ok=True)
            with open(os.path.join(cfg, "wallpaper"), "w", encoding="utf-8") as fh:
                fh.write(path + "\n")
            run(["systemctl", "--user", "restart", "lumo-wallpaper.service"])
        refresh_async(apply, lambda _r: None)

    def _choose(self, _btn):
        dialog = Gtk.FileDialog(title="Choose wallpaper")
        dialog.open(None, None, self._open_done)

    def _open_done(self, dialog, result):
        try:
            file = dialog.open_finish(result)
        except Exception:
            return
        if file:
            self._set(None, file.get_path())


# ============================== Notifications ==============================
class NotificationsPage(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.append(util.page_title("Notifications"))
        self.dnd = util.switch()
        self.dnd.connect("state-set", self._on_dnd)
        self.append(util.row("Do Not Disturb",
                             "Silence notification banners (mako)", self.dnd))
        test = util.button("Send a test notification", flat=True)
        test.connect("clicked", lambda *_: run(
            ["notify-send", "Lumo OS", "Notifications are working just fine."]))
        self.append(util.row("Test", "Show a sample notification", test))
        refresh_async(self._probe, self._apply)

    def _probe(self):
        out = run_out(["makoctl", "mode"])
        return "dnd" in out

    def _apply(self, data):
        self.dnd.handler_block_by_func(self._on_dnd)
        self.dnd.set_active(bool(data))
        self.dnd.handler_unblock_by_func(self._on_dnd)
        return False

    def _on_dnd(self, _sw, state):
        run(["makoctl", "set", "mode", "do-not-disturb" if state else "default"])
        return False


# ============================== Sound ==============================
class SoundPage(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.append(util.page_title("Sound"))
        self.out_combo = Gtk.DropDown()
        self.out_combo.connect("notify::selected-item", self._on_output)
        self.append(util.row("Output device", "Where sound is played", self.out_combo))
        self.vol = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.vol.set_size_request(260, -1)
        self.vol.connect("value-changed", self._on_volume)
        self.append(util.row("Output volume", None, self.vol))
        self.mute = util.switch()
        self.mute.connect("state-set", self._on_mute)
        self.append(util.row("Mute", None, self.mute))
        self.status = util.spinner_label("Reading PipeWire state…")
        self.append(self.status)
        refresh_async(self._probe, self._apply)

    def _probe(self):
        sinks = run_out(["pactl", "list", "short", "sinks"])
        vol = run_out(["bash", "-c",
            "pactl get-sink-volume @DEFAULT_SINK@ | head -n1 | grep -oE '^[[:space:]]*[0-9]+%' | tr -d ' %'"])
        mute = run_out(["pactl", "get-sink-mute", "@DEFAULT_SINK@"]).strip()
        default = run_out(["bash", "-c",
            "pactl get-default-sink"])
        return {"sinks": sinks, "vol": vol, "mute": mute == "Mute: yes",
                "default": default.strip()}

    def _apply(self, data):
        if isinstance(data, Exception):
            self.status.set_text("PipeWire/audio unavailable.")
            return False
        self.status.set_text("")
        lines = [l for l in (data["sinks"] or "").splitlines() if l.strip()]
        names = []
        descs = {}
        for line in lines:
            parts = line.split("\t")
            if len(parts) >= 2:
                names.append(parts[1])
        if names:
            model = Gtk.StringList.new(names)
            self.out_combo.set_model(model)
            if data["default"] in names:
                self.out_combo.set_selected(names.index(data["default"]))
        try:
            self.vol.handler_block_by_func(self._on_volume)
            self.vol.set_value(int(data["vol"] or 50))
            self.vol.handler_unblock_by_func(self._on_volume)
        except ValueError:
            pass
        self.mute.handler_block_by_func(self._on_mute)
        self.mute.set_active(data["mute"])
        self.mute.handler_unblock_by_func(self._on_mute)
        return False

    def _on_output(self, combo, _pspec):
        try:
            item = combo.get_selected_item()
            if item:
                run(["pactl", "set-default-sink", item.get_string()])
        except Exception:
            pass

    def _on_volume(self, scale):
        run(["pactl", "set-sink-volume", "@DEFAULT_SINK@",
             f"{int(scale.get_value())}%"])

    def _on_mute(self, _sw, state):
        run(["pactl", "set-sink-mute", "@DEFAULT_SINK@",
             "1" if state else "0"])
        return False


# ============================== Power ==============================
class PowerPage(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.append(util.page_title("Power"))
        suspend = util.button("Suspend now")
        suspend.connect("clicked", lambda *_: run(["systemctl", "suspend"]))
        self.append(util.row("Sleep", "Put this device to sleep", suspend))

        self.gm = util.switch()
        self.gm.connect("state-set", self._on_gm)
        self.append(util.row("Game Mode",
                             "CPU governor 'performance' while plugged in", self.gm))
        refresh_async(lambda: run_out(["pkexec", "/usr/bin/lumo-perf", "status"]),
                      self._apply_gm)

        lock = util.button("Lock screen")
        lock.connect("clicked", lambda *_: run(["/usr/libexec/lumo/lumo-lock"]))
        self.append(util.row("Screen lock", "Lock immediately", lock))

        info = util.spinner_label("")
        self.append(util.row("Idle behavior",
                             "Locks after 15 min, suspends after 40 min (swayidle)",
                             None))
        self.append(info)

    def _apply_gm(self, result):
        if isinstance(result, str):
            self.gm.handler_block_by_func(self._on_gm)
            self.gm.set_active(result.strip() == "on")
            self.gm.handler_unblock_by_func(self._on_gm)
        return False

    def _on_gm(self, _sw, state):
        def apply():
            run(["pkexec", "/usr/bin/lumo-perf", "on" if state else "off"])
        refresh_async(apply, lambda _r: None)
        return False
