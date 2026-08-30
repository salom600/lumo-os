"""Lumo Settings - main application (sidebar + pages)."""
import sys

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

sys.path.insert(0, "/usr/lib/python3/dist-packages")
from lumo import style  # noqa: E402

from . import pages_core, pages_system  # noqa: E402

PAGES = [
    ("Wi-Fi", "network-wireless-symbolic", pages_core.WifiPage),
    ("Bluetooth", "bluetooth-active-symbolic", pages_core.BluetoothPage),
    ("Network", "network-wired-symbolic", pages_core.NetworkPage),
    ("Background", "wallpaper-symbolic", pages_core.BackgroundPage),
    ("Appearance", "applications-graphics-symbolic", pages_core.AppearancePage),
    ("Notifications", "preferences-system-notifications-symbolic",
     pages_core.NotificationsPage),
    ("Sound", "audio-speakers-symbolic", pages_core.SoundPage),
    ("Power", "battery-full-symbolic", pages_core.PowerPage),
    ("Displays", "video-display-symbolic", pages_system.DisplaysPage),
    ("Mouse & Touchpad", "input-mouse-symbolic", pages_system.InputPage),
    ("Keyboard", "input-keyboard-symbolic", pages_system.KeyboardPage),
    ("Printers", "printer-symbolic", pages_system.PrintersPage),
    ("Region & Language", "preferences-desktop-locale-symbolic",
     pages_system.RegionPage),
    ("Accessibility", "preferences-desktop-accessibility-symbolic",
     pages_system.A11yPage),
    ("Users", "system-users-symbolic", pages_system.UsersPage),
    ("Date & Time", "clock-symbolic", pages_system.DateTimePage),
    ("Default Applications", "preferences-desktop-default-applications-symbolic",
     pages_system.DefaultsPage),
    ("About", "help-about-symbolic", pages_system.AboutPage),
]


class SettingsApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.lumo.Settings")
        self.win = None
        self.stack = None
        self.side = None

    def do_activate(self):
        self.win = Gtk.ApplicationWindow(application=self, decorated=False)
        win = self.win
        style.apply_to_display()
        win.set_default_size(1020, 680)

        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        root.add_css_class("lumo-root")

        sidebar_scroll = Gtk.ScrolledWindow(width_request=230,
                                            hscrollbar_policy=Gtk.PolicyType.NEVER)
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        sidebar.set_margin_top(14)
        sidebar.set_margin_bottom(14)
        sidebar.set_margin_start(8)
        sidebar.set_margin_end(4)

        brand = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        logo = Gtk.Image.new_from_file("/usr/share/icons/hicolor/scalable/apps/lumo-logo.svg")
        logo.set_pixel_size(26)
        brand.append(logo)
        blab = Gtk.Label(label="Settings", halign=Gtk.Align.START)
        blab.add_css_class("lumo-title")
        brand.append(blab)
        sidebar.append(brand)

        search = Gtk.Entry()
        search.add_css_class("lumo-entry")
        search.set_placeholder_text("Search settings")
        search.set_margin_top(8)
        search.connect("changed", self._on_search)
        sidebar.append(search)

        self.side = Gtk.ListBox()
        self.side.add_css_class("lumo-sidebar")
        self.side.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.rows = []
        for name, icon, cls in PAGES:
            row = Gtk.ListBoxRow()
            row._page_name = name.lower()
            row._page_cls = cls
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            img = Gtk.Image.new_from_icon_name(icon)
            img.set_pixel_size(16)
            box.append(img)
            lab = Gtk.Label(label=name, halign=Gtk.Align.START)
            box.append(lab)
            row.set_child(box)
            self.side.append(row)
            self.rows.append(row)
        self.side.connect("row-selected", self._on_select)
        sidebar.append(self.side)
        sidebar_scroll.set_child(sidebar)
        root.append(sidebar_scroll)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        content.set_margin_top(18)
        content.set_margin_bottom(18)
        content.set_margin_end(20)
        content.set_margin_start(8)
        content.set_hexpand(True)

        self.page_title = Gtk.Label(label="Wi-Fi", halign=Gtk.Align.START)
        self.page_title.add_css_class("lumo-title")
        content.append(self.page_title)

        scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.stack = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        scroll.set_child(self.stack)
        content.append(scroll)
        root.append(content)

        esc = Gtk.EventControllerKey()
        esc.connect("key-pressed", self._on_key)
        win.add_controller(esc)

        win.set_child(root)
        win.present()

        def _lumo_map_mark(_w=None):
            # CI hook: lets the test harness wait for the actual map event
            print("LUMO_MAP_OK", flush=True)
            return False

        win.connect("map", _lumo_map_mark)
        self.side.select_row(self.rows[0])

    def _on_select(self, _list, row):
        if row is None:
            return
        # clear the page stack
        while self.stack.get_first_child():
            self.stack.remove(self.stack.get_first_child())
        cls = row._page_cls
        page = cls()
        self.stack.append(page)
        self.page_title.set_text(row._page_name.title() if len(row._page_name) < 4
                                 else row._page_name[0].upper() + row._page_name[1:])

    def _on_search(self, entry):
        text = entry.get_text().strip().lower()
        for row in self.rows:
            row.set_visible(not text or text in row._page_name)

    def _on_key(self, _c, keyval, _kc, _m):
        if keyval == 65307:
            self.quit()
            return True
        return False


if __name__ == "__main__":
    SettingsApp().run(sys.argv)
