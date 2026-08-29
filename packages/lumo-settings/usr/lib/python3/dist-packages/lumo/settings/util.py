"""Shared helpers for Lumo Settings pages."""
import subprocess

from gi.repository import Gtk


def run(cmd, timeout=8, check=False):
    """Run a command; return (ok, stdout, stderr)."""
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (res.returncode == 0, res.stdout, res.stderr)
    except Exception as exc:
        return (False, "", str(exc))


def run_out(cmd, timeout=8):
    ok, out, _ = run(cmd, timeout)
    return out if ok else ""


def page_title(text):
    lab = Gtk.Label(label=text, halign=Gtk.Align.START)
    lab.add_css_class("lumo-title")
    return lab


def card():
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    box.add_css_class("lumo-card")
    return box


def row(title, subtitle=None, child=None):
    """A settings row: text at the start, optional widget at the end."""
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    box.add_css_class("lumo-row")
    vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    t = Gtk.Label(label=title, halign=Gtk.Align.START, wrap=True, xalign=0)
    t.add_css_class("lumo-heading")
    vb.append(t)
    if subtitle:
        s = Gtk.Label(label=subtitle, halign=Gtk.Align.START, wrap=True, xalign=0)
        s.add_css_class("lumo-dim")
        vb.append(s)
    box.append(vb)
    if child is not None:
        child.set_valign(Gtk.Align.CENTER)
        child.set_halign(Gtk.Align.END)
        child.set_hexpand(True)
        box.append(child)
    return box


def switch(active=False):
    sw = Gtk.Switch(active=active, valign=Gtk.Align.CENTER)
    return sw


def button(label, flat=False):
    b = Gtk.Button(label=label)
    b.add_css_class("lumo-btn-flat" if flat else "lumo-btn")
    return b


def spinner_label(text):
    lab = Gtk.Label(label=text, halign=Gtk.Align.START)
    lab.add_css_class("lumo-dim")
    return lab
