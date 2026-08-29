"""Lumo Store - PackageKit DBus client (async transactions, real progress)."""
import gi

from gi.repository import Gio, GLib  # noqa: E402

BUS = "org.freedesktop.PackageKit"
PATH = "/org/freedesktop/PackageKit"
IFACE = "org.freedesktop.PackageKit"
TX_IFACE = "org.freedesktop.PackageKit.Transaction"


class PKError(Exception):
    pass


class Transaction:
    """Wraps a PackageKit transaction with UI-safe callbacks (via idle_add)."""

    def __init__(self, tx_path, on_package=None, on_progress=None,
                 on_status=None, on_finished=None, on_error=None):
        self.on_package = on_package
        self.on_progress = on_progress
        self.on_status = on_status
        self.on_finished = on_finished
        self.on_error = on_error
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        self.proxy = Gio.DBusProxy.new_sync(
            bus, Gio.DBusProxyFlags.NONE, None, BUS, tx_path, TX_IFACE, None)
        self.proxy.connect("g-signal", self._on_signal)

    def call(self, method, params):
        try:
            self.proxy.call_sync(method, params, Gio.DBusCallFlags.NONE, -1, None)
        except GLib.Error as exc:
            if self.on_error:
                GLib.idle_add(self.on_error, exc.message)
            else:
                raise PKError(exc.message)

    def _on_signal(self, _proxy, _sender, signal, params):
        try:
            if signal == "Package" and self.on_package:
                info, package_id, summary = params
                GLib.idle_add(self.on_package, str(info), str(package_id), str(summary))
            elif signal == "ItemProgress" and self.on_progress:
                _pid, status, percent = params
                if percent in (0, 101):
                    percent = None
                GLib.idle_add(self.on_progress, str(status), percent)
            elif signal == "ErrorCode" and self.on_error:
                _code, detail = params
                GLib.idle_add(self.on_error, str(detail))
            elif signal == "StatusChanged" and self.on_status:
                GLib.idle_add(self.on_status, str(params[0]))
            elif signal == "Finished" and self.on_finished:
                exit_code, _runtime = params
                GLib.idle_add(self.on_finished, str(exit_code))
        except Exception as exc:
            print(f"[lumo-store] transaction signal error: {exc}")


class Client:
    """Thin PackageKit client."""

    def __init__(self):
        self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)

    def _new_transaction(self, **cbs):
        try:
            res = self.bus.call_sync(
                BUS, PATH, IFACE, "CreateTransaction", None,
                GLib.VariantType.new("(o)"), Gio.DBusCallFlags.NONE, -1, None)
        except GLib.Error as exc:
            raise PKError(f"PackageKit unavailable: {exc.message}")
        tx_path = res.unpack()[0]
        return Transaction(tx_path, **cbs)

    def install(self, package_ids, on_package=None, on_progress=None,
                on_status=None, on_finished=None, on_error=None):
        tx = self._new_transaction(on_package=on_package, on_progress=on_progress,
                                   on_status=on_status, on_finished=on_finished,
                                   on_error=on_error)
        tx.call("InstallPackage", GLib.Variant.new_tuple(
            GLib.Variant.new_uint64(1),  # only-trusted
            GLib.Variant.new_strv(package_ids)))

    def remove(self, package_ids, on_package=None, on_progress=None,
               on_status=None, on_finished=None, on_error=None):
        tx = self._new_transaction(on_package=on_package, on_progress=on_progress,
                                   on_status=on_status, on_finished=on_finished,
                                   on_error=on_error)
        tx.call("RemovePackage", GLib.Variant.new_tuple(
            GLib.Variant.new_uint64(0),
            GLib.Variant.new_strv(package_ids)))

    def update_all(self, package_ids, on_package=None, on_progress=None,
                   on_status=None, on_finished=None, on_error=None):
        tx = self._new_transaction(on_package=on_package, on_progress=on_progress,
                                   on_status=on_status, on_finished=on_finished,
                                   on_error=on_error)
        tx.call("UpdatePackages", GLib.Variant.new_tuple(
            GLib.Variant.new_uint64(1),
            GLib.Variant.new_strv(package_ids)))

    def refresh_cache(self, on_finished=None, on_error=None, on_status=None):
        tx = self._new_transaction(on_finished=on_finished, on_error=on_error,
                                   on_status=on_status)
        tx.call("RefreshCache", GLib.Variant.new_tuple(GLib.Variant.new_boolean(True)))

    def get_updates(self, on_package=None, on_finished=None, on_error=None):
        tx = self._new_transaction(on_package=on_package, on_finished=on_finished,
                                   on_error=on_error)
        tx.call("GetUpdates", GLib.Variant.new_tuple(GLib.Variant.new_uint64(0)))
