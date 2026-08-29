"""Lumo Store - AppStream catalog access (Debian swcatalog XML).

Parses the AppStream metadata produced by Debian's apt integration
(/var/lib/swcatalog/xml/*.xml.gz) into lightweight App objects.
"""
import glob
import gzip
import os
import re
import xml.etree.ElementTree as ET

CATALOG_DIRS = [
    "/var/lib/swcatalog/xml",     # appstream >= 1.0 layout (trixie)
    "/var/lib/app-info/xmls",     # older fallback
]

ICON_CACHE_ROOT = "/usr/share/app-info/icons"

CATEGORY_MAP = {
    "Internet": ["Network"],
    "Browsers": ["WebBrowser"],
    "Games": ["Game"],
    "Multimedia": ["AudioVideo", "Audio", "Video"],
    "Graphics": ["Graphics"],
    "Office": ["Office"],
    "Utilities": ["Utility"],
    "System": ["System"],
    "Development": ["Development"],
    "Education": ["Education"],
    "Science": ["Science"],
    "Accessibility": ["Accessibility"],
}


def _strip_tags(html):
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


class App:
    __slots__ = ("id", "name", "summary", "description", "categories",
                 "desktop_id", "cached_icons", "remote_icons", "screenshots",
                 "package", "version")

    def __init__(self):
        self.id = ""
        self.name = ""
        self.summary = ""
        self.description = ""
        self.categories = []
        self.desktop_id = None
        self.cached_icons = []   # "repo|name" refs or plain paths
        self.remote_icons = []   # urls
        self.screenshots = []    # image urls
        self.package = ""
        self.version = ""

    def matches(self, text):
        t = text.lower()
        return (t in self.name.lower() or t in self.summary.lower()
                or t in self.id.lower() or t in self.description.lower())

    def in_category(self, category):
        if category == "All":
            return True
        if category in CATEGORY_MAP:
            return bool(set(self.categories) & set(CATEGORY_MAP[category]))
        if category == "Fonts":
            return self.id.endswith(".font") or "Fonts" in self.categories
        if category == "Themes":
            return ("Themes" in self.categories
                    or "theme" in self.id.lower())
        return False

    def icon_path(self, size="64x64"):
        """Best-effort local icon path from the appstream icon cache."""
        for ref in self.cached_icons:
            if os.path.isfile(ref):
                return ref
            if "|" in ref:
                repo, name = ref.split("|", 1)
                for cand in (
                    os.path.join(ICON_CACHE_ROOT, repo, size, f"{name}.png"),
                    os.path.join(ICON_CACHE_ROOT, repo, "64x64", f"{name}.png"),
                    os.path.join(ICON_CACHE_ROOT, repo, "128x128", f"{name}.png"),
                ):
                    if os.path.isfile(cand):
                        return cand
        return None


def _parse_component(comp):
    app = App()
    id_el = comp.find("id")
    if id_el is not None and id_el.text:
        app.id = id_el.text.strip()
    comp_type = comp.get("type") or ""
    if comp_type in ("runtime", "operating-system", "repository"):
        return None
    if not app.id:
        return None

    def find(tag):
        return comp.find(tag)

    name_el = find("name")
    if name_el is not None and name_el.text:
        app.name = name_el.text.strip()
    sum_el = find("summary")
    if sum_el is not None and sum_el.text:
        app.summary = sum_el.text.strip()
    desc = find("description")
    if desc is not None:
        app.description = _strip_tags("".join(desc.itertext()))
    for cat in comp.findall("categories/category"):
        if cat.text:
            app.categories.append(cat.text.strip())
    launch = find("provides/launchable")
    if launch is not None and launch.text:
        app.desktop_id = launch.text.strip()
    pkg = find("pkgname")
    if pkg is not None and pkg.text:
        app.package = pkg.text.strip()
    for bundle in comp.findall("provides/bundle"):
        if bundle.text and not app.package:
            app.package = bundle.text.strip()
    ver = find("releases/release")
    if ver is not None and ver.get("version"):
        app.version = ver.get("version")
    for icon in comp.findall("icons/icon"):
        if icon.text:
            t = icon.get("type")
            if t == "cached":
                app.cached_icons.append(icon.text.strip())
            elif t == "remote":
                app.remote_icons.append(icon.text.strip())
    for shot in comp.findall("screenshots/screenshot"):
        for img in shot.findall("image"):
            if img.text and img.get("type") in (None, "source"):
                app.screenshots.append(img.text.strip())
                break
    if not app.package and app.id:
        base = app.id.split("/")[-1]
        app.package = base.rsplit(".", 1)[-1].lower() if "." in base else base
    if not app.name:
        return None
    return app


def load_catalog():
    """Parse all AppStream catalogs; returns list of App."""
    apps = {}
    paths = []
    for d in CATALOG_DIRS:
        paths.extend(sorted(glob.glob(os.path.join(d, "*.xml"))))
        paths.extend(sorted(glob.glob(os.path.join(d, "*.xml.gz"))))
    for path in paths:
        try:
            opener = gzip.open if path.endswith(".gz") else open
            with opener(path, "rb") as fh:
                data = fh.read()
            root = ET.fromstring(data)
        except Exception as exc:
            print(f"[lumo-store] skipping catalog {path}: {exc}")
            continue
        for comp in root.iter():
            if not comp.tag.endswith("component"):
                continue
            try:
                app = _parse_component(comp)
            except Exception:
                app = None
            if app is None:
                continue
            existing = apps.get(app.id)
            if existing:
                if app.screenshots and not existing.screenshots:
                    existing.screenshots = app.screenshots
                if app.remote_icons and not existing.remote_icons:
                    existing.remote_icons = app.remote_icons
                if app.cached_icons and not existing.cached_icons:
                    existing.cached_icons = app.cached_icons
                if app.desktop_id and not existing.desktop_id:
                    existing.desktop_id = app.desktop_id
            else:
                apps[app.id] = app
    return list(apps.values())


def installed_map():
    """Return {package: True} for all installed packages (fast single call)."""
    import subprocess
    result = {}
    try:
        out = subprocess.run(
            ["dpkg-query", "-W", "-f=${Package}|${db:Status-Abbrev}\n"],
            capture_output=True, text=True, timeout=20)
        for line in out.stdout.splitlines():
            if "|" not in line:
                continue
            name, status = line.split("|", 1)
            if len(status) >= 3 and status[0] == "i" and status[2] == "i":
                result[name] = True
    except Exception:
        pass
    return result
