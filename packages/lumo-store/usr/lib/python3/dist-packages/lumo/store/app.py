"""Lumo Store - main application UI (GTK4).

Real package management through PackageKit: browse/search AppStream data,
install, remove, update, refresh metadata, detect drivers, game tools.
"""
import os
import sys
import threading
import urllib.request

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gio, Gtk  # noqa: E402

sys.path.insert(0, "/usr/lib/python3/dist-packages")
from lumo import style  # noqa: E402
from lumo.store import catalog, drivers as drvmod, pk  # noqa: E402

CACHE_DIR = os.path.expanduser("~/.cache/lumo-store")

CATEGORIES = [
    "All", "Internet", "Browsers", "Games", "Multimedia", "Graphics",
    "Office", "Utilities", "System", "Development", "Education",
    "Accessibility", "Fonts", "Themes",
]
SPECIAL = ["Installed", "Updates", "Drivers", "Game Tools"]


class StoreApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.lumo.Store")
        self.apps = []
        self.installed = {}
        self.win = None
        self.current = None
        self.pk = None
        self.busy = False

    def do_activate(self):
        self.win = Gtk.ApplicationWindow(application=self, decorated=False)
        win = self.win
        style.apply_to_display()
        win.set_default_size(1080, 700)

        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        root.add_css_class("lumo-root")

        # ---------- sidebar ----------
        sidebar_scroll = Gtk.ScrolledWindow(width_request=210,
                                            hscrollbar_policy=Gtk.PolicyType.NEVER)
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        sidebar.add_css_class("lumo-sidebar")
        sidebar.set_margin_top(12)

        def side_label(text):
            lab = Gtk.Label(label=text, halign=Gtk.Align.START)
            lab.add_css_class("lumo-heading")
            lab.set_margin_start(12)
            lab.set_margin_bottom(4)
            return lab

        sidebar.append(side_label("Software"))
        self.cat_rows = {}
        for cat in CATEGORIES + SPECIAL:
            row = Gtk.ListBoxRow()
            row._category = cat
            lab = Gtk.Label(label=cat, halign=Gtk.Align.START)
            lab.set_margin_start(12)
            row.set_child(lab)
            self.cat_rows[cat] = row
        self.side_list = Gtk.ListBox()
        self.side_list.add_css_class("lumo-sidebar")
        self.side_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        for cat in CATEGORIES + SPECIAL:
            self.side_list.append(self.cat_rows[cat])
        self.side_list.connect("row-selected", self._on_category)
        sidebar.append(self.side_list)
        sidebar_scroll.set_child(sidebar)
        root.append(sidebar_scroll)

        # ---------- content ----------
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(14)
        content.set_margin_bottom(14)
        content.set_margin_end(16)
        content.set_margin_start(6)
        content.set_hexpand(True)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.title_label = Gtk.Label(label="Discover", halign=Gtk.Align.START)
        self.title_label.add_css_class("lumo-title")
        header.append(self.title_label)

        self.search = Gtk.Entry(hexpand=True)
        self.search.add_css_class("lumo-entry")
        self.search.set_placeholder_text("Search software…")
        self.search.set_halign(Gtk.Align.END)
        self.search.set_size_request(300, -1)
        self.search.connect("changed", self._on_search)
        header.append(self.search)
        content.append(header)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        content.append(self.stack)
        self.stack.set_vexpand(True)

        self.view_browse = self._build_browse()
        self.view_detail = self._build_detail()
        self.view_updates = self._build_updates()
        self.view_drivers = self._build_drivers()
        self.view_gaming = self._build_gaming()
        for name, view in (("browse", self.view_browse), ("detail", self.view_detail),
                           ("updates", self.view_updates), ("drivers", self.view_drivers),
                           ("gaming", self.view_gaming)):
            self.stack.add_named(view, name)

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

        # initial data
        threading.Thread(target=self._load_data, daemon=True).start()

    # ================= data =================
    def _load_data(self):
        self.installed = catalog.installed_map()
        apps = catalog.load_catalog()
        GLib.idle_add(self._after_load, apps)

    def _after_load(self, apps):
        self.apps = apps
        self.browse_status.set_visible(not apps)
        if not apps:
            self.browse_status.set_text(
                "No application metadata yet - click Updates > 'Check for updates' "
                "(RefreshCache) or run 'apt update' to download AppStream catalogs.")
        self._select("All")
        return False

    def _pk_client(self):
        if self.pk is None:
            self.pk = pk.Client()
        return self.pk

    # ================= views =================
    def _build_browse(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.browse_status = Gtk.Label(visible=False, halign=Gtk.Align.CENTER, wrap=True)
        self.browse_status.add_css_class("lumo-subtitle")
        outer.append(self.browse_status)
        scrolled = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.flow = Gtk.FlowBox(
            orientation=Gtk.Orientation.HORIZONTAL,
            max_children_per_line=4, min_children_per_line=3,
            column_spacing=10, row_spacing=10, vexpand=True)
        self.flow.set_valign(Gtk.Align.START)
        scrolled.set_child(self.flow)
        outer.append(scrolled)
        return outer

    def _build_detail(self):
        scrolled = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.set_margin_top(6)
        self.detail_box = box
        scrolled.set_child(box)
        return scrolled

    def _build_updates(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        lab = Gtk.Label(label="Pending updates", halign=Gtk.Align.START, hexpand=True)
        lab.add_css_class("lumo-heading")
        head.append(lab)
        refresh = Gtk.Button(label="Check for updates")
        refresh.add_css_class("lumo-btn-flat")
        refresh.connect("clicked", self._check_updates)
        head.append(refresh)
        update_all = Gtk.Button(label="Update All")
        update_all.add_css_class("lumo-btn")
        update_all.connect("clicked", self._update_all)
        head.append(update_all)
        box.append(head)
        self.updates_status = Gtk.Label(label="Click 'Check for updates'.")
        self.updates_status.add_css_class("lumo-dim")
        self.updates_status.set_halign(Gtk.Align.START)
        box.append(self.updates_status)
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.updates_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        scroll.set_child(self.updates_list)
        box.append(scroll)
        return box

    def _build_drivers(self):
        scrolled = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        lab = Gtk.Label(label="Drivers & firmware", halign=Gtk.Align.START)
        lab.add_css_class("lumo-heading")
        box.append(lab)
        sub = Gtk.Label(
            label="Detected hardware recommendations. Open-source drivers are already "
                  "active; installs are offered only when proprietary bits or missing "
                  "firmware are genuinely needed.",
            halign=Gtk.Align.START, wrap=True)
        sub.add_css_class("lumo-dim")
        box.append(sub)
        self.drivers_rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.append(self.drivers_rows)
        threading.Thread(target=self._load_drivers, daemon=True).start()
        scrolled.set_child(box)
        return scrolled

    def _load_drivers(self):
        recs = drvmod.recommendations()
        GLib.idle_add(self._show_drivers, recs)

    def _show_drivers(self, recs):
        while self.drivers_rows.get_first_child():
            self.drivers_rows.remove(self.drivers_rows.get_first_child())
        for rec in recs:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            row.add_css_class("lumo-row")
            vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            t = Gtk.Label(label=rec["title"], halign=Gtk.Align.START)
            t.add_css_class("lumo-heading")
            vb.append(t)
            d = Gtk.Label(label=rec["desc"], halign=Gtk.Align.START, wrap=True)
            d.add_css_class("lumo-dim")
            d.set_xalign(0)
            vb.append(d)
            row.append(vb)
            if rec["packages"]:
                btn = Gtk.Button(label="Install")
                btn.add_css_class("lumo-btn")
                btn.set_halign(Gtk.Align.END)
                btn.set_valign(Gtk.Align.CENTER)
                btn.connect("clicked", self._install_pkgs, rec["packages"], btn)
                row.append(btn)
            else:
                ok = Gtk.Label(label="OK")
                ok.add_css_class("lumo-success-label")
                ok.set_valign(Gtk.Align.CENTER)
                row.append(ok)
            self.drivers_rows.append(row)
        return False

    def _build_gaming(self):
        scrolled = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        lab = Gtk.Label(label="Gaming", halign=Gtk.Align.START)
        lab.add_css_class("lumo-heading")
        box.append(lab)
        sub = Gtk.Label(
            label="Everything a gaming session needs: Steam, Proton-ready Wine, "
                  "performance profiles, overlays and controller tools. Install what "
                  "you use - nothing runs in the background by default.",
            halign=Gtk.Align.START, wrap=True)
        sub.add_css_class("lumo-dim")
        box.append(sub)

        gm_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        gm_row.add_css_class("lumo-row")
        gm_vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        gm_t = Gtk.Label(label="Game Mode", halign=Gtk.Align.START)
        gm_t.add_css_class("lumo-heading")
        gm_vb.append(gm_t)
        gm_d = Gtk.Label(label="Switch CPU governor to 'performance' while gaming "
                              "(also available from Quick Settings).",
                         halign=Gtk.Align.START, wrap=True)
        gm_d.add_css_class("lumo-dim")
        gm_vb.append(gm_d)
        gm_row.append(gm_vb)
        gm_btn = Gtk.Button(label="Toggle")
        gm_btn.add_css_class("lumo-btn")
        gm_btn.set_valign(Gtk.Align.CENTER)
        gm_btn.connect("clicked", self._toggle_gamemode)
        gm_row.append(gm_btn)
        box.append(gm_row)

        self.installed = catalog.installed_map()
        for tool in drvmod.GAME_TOOLS:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            row.add_css_class("lumo-row")
            vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            t = Gtk.Label(label=tool["name"], halign=Gtk.Align.START)
            t.add_css_class("lumo-heading")
            vb.append(t)
            d = Gtk.Label(label=tool["desc"], halign=Gtk.Align.START, wrap=True)
            d.add_css_class("lumo-dim")
            vb.append(d)
            row.append(vb)
            btn = Gtk.Button()
            btn.set_valign(Gtk.Align.CENTER)
            if tool["id"] in self.installed:
                btn.set_label("Installed")
                btn.set_sensitive(False)
            else:
                btn.set_label("Install")
                btn.add_css_class("lumo-btn")
                btn.connect("clicked", self._install_pkgs, [tool["id"]], btn)
            row.append(btn)
            box.append(row)

        test_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        test_row.add_css_class("lumo-row")
        vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        t = Gtk.Label(label="Controller test", halign=Gtk.Align.START)
        t.add_css_class("lumo-heading")
        vb.append(t)
        d = Gtk.Label(label="Open a terminal running jstest to verify buttons and axes "
                              "of connected gamepads.",
                      halign=Gtk.Align.START, wrap=True)
        d.add_css_class("lumo-dim")
        vb.append(d)
        test_row.append(vb)
        tbtn = Gtk.Button(label="Open")
        tbtn.add_css_class("lumo-btn-flat")
        tbtn.set_valign(Gtk.Align.CENTER)
        tbtn.connect("clicked", lambda *_: self._spawn(
            ["foot", "-e", "bash", "-lc",
             "command -v jstest >/dev/null && jstest --normal /dev/input/js0 "
             "|| echo 'Install the joystick tools first, then replug your controller.'"]))
        test_row.append(tbtn)
        box.append(test_row)

        scrolled.set_child(box)
        return scrolled

    # ================= browse logic =================
    def _select(self, category, query=""):
        self.current = (category, query)
        for cat, row in self.cat_rows.items():
            if cat == category:
                self.side_list.select_row(row)
        while self.flow.get_last_child():
            self.flow.remove(self.flow.get_last_child())

        if category == "Updates":
            self.stack.set_visible_child(self.view_updates)
            self.title_label.set_text("Updates")
            self._check_updates()
            return
        if category == "Drivers":
            self.stack.set_visible_child(self.view_drivers)
            self.title_label.set_text("Drivers")
            return
        if category == "Game Tools":
            self.stack.set_visible_child(self.view_gaming)
            self.title_label.set_text("Game Tools")
            return

        self.stack.set_visible_child(self.view_browse)
        titles = {"Installed": "Installed applications", "All": "Discover",
                  "Browsers": "Browsers"}
        self.title_label.set_text(titles.get(category, category))

        if category == "Installed":
            pool = [a for a in self.apps if a.package in self.installed]
        else:
            pool = self.apps
        if query:
            pool = [a for a in pool if a.matches(query)]
        else:
            pool = [a for a in pool if a.in_category(category)]

        pool = sorted(pool, key=lambda a: a.name.lower())[:240]
        for app in pool:
            self.flow.append(self._app_cell(app))

    def _app_cell(self, app):
        is_installed = app.package in self.installed
        cell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        cell.add_css_class("lumo-appcell")

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        icon = Gtk.Image()
        icon.set_pixel_size(52)
        path = app.icon_path()
        if path:
            try:
                icon.set_from_file(path)
            except Exception:
                icon.set_from_icon_name("application-x-executable")
        else:
            icon.set_from_icon_name("application-x-executable")
        top.append(icon)

        vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        t = Gtk.Label(label=app.name, halign=Gtk.Align.START, wrap=True, xalign=0)
        t.add_css_class("title")
        vb.append(t)
        s = Gtk.Label(label=(app.summary or "")[:70], halign=Gtk.Align.START, wrap=True,
                      xalign=0)
        s.add_css_class("desc")
        vb.append(s)
        top.append(vb)
        cell.append(top)

        bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        if is_installed:
            badge = Gtk.Label(label="Installed")
            badge.add_css_class("lumo-badge")
            bottom.append(badge)
        if app.version:
            v = Gtk.Label(label=app.version)
            v.add_css_class("lumo-dim")
            bottom.append(v)
        cell.append(bottom)

        btn = Gtk.Button()
        btn.set_child(cell)
        btn.set_has_frame(False)
        btn.connect("clicked", self._open_detail, app)
        return btn

    def _on_category(self, _list, row):
        if row is None:
            return
        self.search.set_text("")
        self._select(row._category)

    def _on_search(self, entry):
        text = entry.get_text().strip()
        cat = "All" if text else (self.current[0] if self.current else "All")
        self._select(cat, query=text)

    # ================= detail =================
    def _open_detail(self, _btn, app):
        self.current_app = app
        while self.detail_box.get_first_child():
            self.detail_box.remove(self.detail_box.get_first_child())

        is_installed = app.package in self.installed

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        icon = Gtk.Image()
        icon.set_pixel_size(84)
        path = app.icon_path()
        if path:
            icon.set_from_file(path)
        else:
            icon.set_from_icon_name("application-x-executable")
        head.append(icon)

        vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, valign=Gtk.Align.CENTER)
        t = Gtk.Label(label=app.name, halign=Gtk.Align.START)
        t.add_css_class("lumo-title")
        vb.append(t)
        s = Gtk.Label(label=app.summary, halign=Gtk.Align.START, wrap=True, xalign=0)
        s.add_css_class("lumo-subtitle")
        vb.append(s)
        meta = Gtk.Label(label=f"{app.package or 'system'}  ·  {'installed' if is_installed else 'not installed'}"
                          + (f"  ·  {app.version}" if app.version else ""),
                         halign=Gtk.Align.START, xalign=0)
        meta.add_css_class("lumo-dim")
        vb.append(meta)
        head.append(vb)

        self.action_btn = Gtk.Button()
        self.action_btn.set_valign(Gtk.Align.CENTER)
        self.action_btn.set_halign(Gtk.Align.END)
        self.action_btn.set_hexpand(True)
        if is_installed:
            self.action_btn.set_label("Remove")
            self.action_btn.add_css_class("lumo-btn-danger")
            self.action_btn.connect("clicked", self._remove_current)
        else:
            self.action_btn.set_label("Install")
            self.action_btn.add_css_class("lumo-btn")
            self.action_btn.connect("clicked", self._install_current)
        head.append(self.action_btn)
        self.detail_box.append(head)

        self.progress = Gtk.ProgressBar(visible=False)
        self.progress.add_css_class("lumo-progress")
        self.detail_box.append(self.progress)
        self.progress_label = Gtk.Label(label="", visible=False, halign=Gtk.Align.START)
        self.progress_label.add_css_class("lumo-dim")
        self.detail_box.append(self.progress_label)

        if app.screenshots:
            shot = Gtk.Picture()
            shot.set_size_request(-1, 260)
            shot.add_css_class("lumo-card")
            self.detail_box.append(shot)
            self._load_shot_async(shot, app.screenshots[0])

        if app.description:
            desc_label = Gtk.Label(label=app.description, halign=Gtk.Align.START,
                                   wrap=True, xalign=0)
            self.detail_box.append(desc_label)

        back = Gtk.Button(label="← Back")
        back.add_css_class("lumo-btn-flat")
        back.set_halign(Gtk.Align.START)
        back.connect("clicked", lambda *_: self._select(self.current[0] if self.current else "All"))
        self.detail_box.append(back)

        self.stack.set_visible_child(self.view_detail)
        self.title_label.set_text(app.name)

    def _load_shot_async(self, picture, url):
        os.makedirs(CACHE_DIR, exist_ok=True)
        fname = os.path.join(CACHE_DIR, str(abs(hash(url))) + ".img")

        def worker():
            data = None
            if os.path.exists(fname):
                try:
                    with open(fname, "rb") as fh:
                        data = fh.read()
                except Exception:
                    data = None
            if not data:
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "lumo-store/1.0"})
                    with urllib.request.urlopen(req, timeout=12) as resp:
                        data = resp.read()
                    with open(fname, "wb") as fh:
                        fh.write(data)
                except Exception as exc:
                    print(f"[lumo-store] screenshot download failed: {exc}")
            if data:
                GLib.idle_add(self._set_shot, picture, data)

        threading.Thread(target=worker, daemon=True).start()

    def _set_shot(self, picture, data):
        try:
            texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(data))
            picture.set_paintable(texture)
        except Exception as exc:
            print(f"[lumo-store] screenshot decode failed: {exc}")
        return False

    # ================= actions =================
    def _package_id(self, name):
        # arch auto: use native wildcard (x86_64)
        return f"{name};*;*;"

    def _install_current(self, _btn):
        app = self.current_app
        if not app or self.busy:
            return
        self._install_pkgs(self.action_btn, [app.package], self.action_btn)

    def _remove_current(self, _btn):
        app = self.current_app
        if not app or self.busy:
            return
        self._remove_pkg(app.package)

    def _install_pkgs(self, _btn, packages, btn=None):
        if self.busy or not packages:
            return
        self.busy = True
        target_btn = btn or self.action_btn
        target_btn.set_sensitive(False)
        self.progress.set_visible(True)
        self.progress_label.set_visible(True)
        client = self._pk_client()

        def on_package(_info, package_id, _summary):
            self.progress_label.set_text(f"Installing {package_id.split(';')[0]}…")

        def on_progress(_status, percent):
            if percent is not None:
                self.progress.set_fraction(percent / 100.0)

        def on_status(status):
            self.progress_label.set_text(status.replace("-", " "))

        def on_error(msg):
            self.progress_label.set_text(f"Error: {msg}")

        def on_finished(exit_code):
            self.busy = False
            self.progress.set_visible(False)
            ok = exit_code == pk.EXIT_SUCCESS
            self.progress_label.set_visible(not ok)
            target_btn.set_sensitive(True)
            if ok:
                threading.Thread(target=self._reload_installed, daemon=True).start()
                self.progress_label.set_text("Done.")
                self.stack.set_visible_child(self.view_detail)

        try:
            client.install([self._package_id(p) for p in packages],
                           on_package=on_package, on_progress=on_progress,
                           on_status=on_status, on_finished=on_finished,
                           on_error=on_error)
        except pk.PKError as exc:
            self.busy = False
            self.progress.set_visible(False)
            target_btn.set_sensitive(True)
            self.progress_label.set_text(str(exc))
            self.progress_label.set_visible(True)

    def _remove_pkg(self, package):
        if self.busy:
            return
        self.busy = True
        self.action_btn.set_sensitive(False)
        self.progress.set_visible(True)
        self.progress_label.set_visible(True)
        client = self._pk_client()

        def on_finished(exit_code):
            self.busy = False
            self.progress.set_visible(False)
            self.action_btn.set_sensitive(True)
            if exit_code == pk.EXIT_SUCCESS:
                threading.Thread(target=self._reload_installed, daemon=True).start()

        def on_error(msg):
            self.progress_label.set_text(f"Error: {msg}")

        try:
            client.remove([self._package_id(package)],
                          on_finished=on_finished, on_error=on_error,
                          on_status=lambda s: self.progress_label.set_text(s))
        except pk.PKError as exc:
            self.busy = False
            self.action_btn.set_sensitive(True)
            self.progress_label.set_text(str(exc))

    def _reload_installed(self):
        self.installed = catalog.installed_map()
        GLib.idle_add(lambda: (self._select(self.current[0] if self.current else "All"), False)[1])

    def _refresh_meta(self, _btn=None):
        client = self._pk_client()
        try:
            client.refresh_cache(
                on_status=lambda s: print("[lumo-store] refresh:", s),
                on_finished=lambda code: threading.Thread(
                    target=self._load_data, daemon=True).start(),
                on_error=lambda msg: print("[lumo-store] refresh error:", msg))
        except pk.PKError as exc:
            print(exc)

    def _check_updates(self, _btn=None):
        client = self._pk_client()
        found = []

        def on_package(info, package_id, summary):
            name = package_id.split(";")[0]
            version = package_id.split(";")[1] if ";" in package_id else ""
            found.append((name, version, summary))

        def on_finished(code):
            GLib.idle_add(self._show_updates, found, code)

        self.updates_status.set_text("Checking for updates…")
        while self.updates_list.get_first_child():
            self.updates_list.remove(self.updates_list.get_first_child())
        try:
            client.get_updates(on_package=on_package, on_finished=on_finished,
                               on_error=lambda m: self.updates_status.set_text(f"Error: {m}"))
        except pk.PKError as exc:
            self.updates_status.set_text(str(exc))

    def _show_updates(self, found, code):
        while self.updates_list.get_first_child():
            self.updates_list.remove(self.updates_list.get_first_child())
        if not found:
            self.updates_status.set_text("System is up to date. Nice.")
            return False
        self.updates_status.set_text(f"{len(found)} updates available.")
        self.update_ids = []
        for name, version, summary in found:
            self.update_ids.append(f"{name};{version};*;")
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            row.add_css_class("lumo-row")
            vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            t = Gtk.Label(label=f"{name}  {version}", halign=Gtk.Align.START)
            t.add_css_class("lumo-heading")
            vb.append(t)
            s = Gtk.Label(label=summary[:90], halign=Gtk.Align.START, xalign=0)
            s.add_css_class("lumo-dim")
            vb.append(s)
            row.append(vb)
            self.updates_list.append(row)
        return False

    def _update_all(self, _btn):
        if getattr(self, "update_ids", None) and not self.busy:
            self.busy = True
            client = self._pk_client()
            self.updates_status.set_text("Updating…")

            def on_finished(code):
                self.busy = False
                GLib.idle_add(self._check_updates)

            try:
                client.update_all(self.update_ids, on_finished=on_finished,
                                  on_error=lambda m: self.updates_status.set_text(m))
            except pk.PKError as exc:
                self.busy = False
                self.updates_status.set_text(str(exc))

    def _toggle_gamemode(self, _btn):
        self._spawn(["pkexec", "/usr/bin/lumo-perf", "toggle"])

    def _spawn(self, argv):
        import subprocess
        try:
            subprocess.Popen(argv, start_new_session=True)
        except Exception as exc:
            print(f"[lumo-store] spawn failed: {exc}")

    def _on_key(self, _c, keyval, _kc, _m):
        if keyval == 65307:
            self.quit()
            return True
        return False


if __name__ == "__main__":
    StoreApp().run(sys.argv)
