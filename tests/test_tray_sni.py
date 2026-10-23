"""End to end: TrayIcon + build_menu_model + SNI backend on a private session bus.

Simulates what KDE Plasma does: left click (Activate), middle click (SecondaryActivate),
reading the menu (GetLayout) and clicking an entry (Event "clicked").
"""
import shutil
import subprocess
import time
from pathlib import Path

import pytest

gi = pytest.importorskip("gi")
from gi.repository import Gio, GLib  # noqa: E402

from pangolin_gui.models import Account, AppState, ConnState  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ACC = Account(user_id="u1", host="https://p.example", email="a@example.com", org_id="o1")
WATCHER_XML = """<node><interface name="org.kde.StatusNotifierWatcher">
<method name="RegisterStatusNotifierItem"><arg type="s" direction="in"/></method>
</interface></node>"""


class Recorder:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *args: self.calls.append(name)


def pump(condition, timeout=3.0):
    ctx = GLib.MainContext.default()
    end = time.time() + timeout
    while time.time() < end:
        while ctx.iteration(False):
            pass
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def call(conn, name, path, iface, method, params, reply_type=None):
    box = {}

    def done(c, res, _d):
        try:
            box["r"] = c.call_finish(res)
        except Exception as exc:
            box["e"] = exc
    conn.call(name, path, iface, method, params,
              GLib.VariantType(reply_type) if reply_type else None,
              Gio.DBusCallFlags.NONE, 3000, None, done, None)
    assert pump(lambda: box)
    if "e" in box:
        raise box["e"]
    return box["r"]


def flatten(item):
    item_id, props, children = item
    yield item_id, props
    for child in children:
        yield from flatten(child)


@pytest.fixture
def session_bus(monkeypatch):
    # Own dbus-daemon instead of Gio.TestDBus: TestDBus.down() blocks 30 s waiting for
    # the cached session-bus singleton that the tray keeps.
    if not shutil.which("dbus-daemon"):
        pytest.skip("dbus-daemon not installed")
    daemon = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address"],
                              stdout=subprocess.PIPE, text=True)
    address = daemon.stdout.readline().strip()
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", address)
    monkeypatch.setenv("PANGOLIN_TRAY", "sni")
    flags = Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION
    watcher_conn = Gio.DBusConnection.new_for_address_sync(address, flags, None, None)
    registered = []

    def on_call(conn, sender, path, iface, method, params, invocation):
        registered.append(params.unpack()[0])
        invocation.return_value(None)
    watcher_conn.register_object("/StatusNotifierWatcher",
                                 Gio.DBusNodeInfo.new_for_xml(WATCHER_XML).interfaces[0], on_call, None, None)
    Gio.bus_own_name_on_connection(watcher_conn, "org.kde.StatusNotifierWatcher",
                                   Gio.BusNameOwnerFlags.NONE, None, None)
    client = Gio.DBusConnection.new_for_address_sync(address, flags, None, None)
    yield client, registered
    daemon.terminate()
    daemon.wait(5)


def test_tray_over_dbus(session_bus):
    from pangolin_gui.tray import TrayIcon

    client, registered = session_bus
    ctl = Recorder()
    tray = TrayIcon(ctl, ROOT / "data" / "icons")
    assert tray.backend_name == "sni"
    tray.update(AppState(conn=ConnState.DISCONNECTED, accounts=[ACC], active_account=ACC))
    assert pump(lambda: registered)
    service = registered[0]

    # Menu as KDE reads it: "Connect" and "Open Status…" are top-level entries
    rev, layout = call(client, service, "/MenuBar", "com.canonical.dbusmenu", "GetLayout",
                       GLib.Variant("(iias)", (0, -1, [])), "(u(ia{sv}av))").unpack()
    top = {props.get("label"): item_id for item_id, props, _c in layout[2]}
    assert "Connect" in top and "Open Status…" in top

    # Right-click menu entry -> controller
    call(client, service, "/MenuBar", "com.canonical.dbusmenu", "Event",
         GLib.Variant("(isvu)", (top["Connect"], "clicked", GLib.Variant("s", ""), 0)))
    assert pump(lambda: "connect" in ctl.calls)

    # Left click opens the status window, middle click toggles the connection
    call(client, service, "/StatusNotifierItem", "org.kde.StatusNotifierItem", "Activate",
         GLib.Variant("(ii)", (0, 0)))
    assert pump(lambda: "open_status" in ctl.calls)
    call(client, service, "/StatusNotifierItem", "org.kde.StatusNotifierItem", "SecondaryActivate",
         GLib.Variant("(ii)", (0, 0)))
    assert pump(lambda: ctl.calls.count("connect") == 2)

    # Real icon files decode into pixmaps; connected state switches to the orange icon
    tray.update(AppState(conn=ConnState.CONNECTED, accounts=[ACC], active_account=ACC))
    get = lambda prop: call(client, service, "/StatusNotifierItem", "org.freedesktop.DBus.Properties",  # noqa: E731
                            "Get", GLib.Variant("(ss)", ("org.kde.StatusNotifierItem", prop)), "(v)").unpack()[0]
    assert get("IconName") == "pangolin-orange"
    pixmaps = get("IconPixmap")
    assert pixmaps and all(len(data) == w * h * 4 for w, h, data in pixmaps)

    # Connected: the same entry now says Disconnect (state-driven, no stale checkbox)
    assert pump(lambda: True, timeout=0.5)
    _rev, layout = call(client, service, "/MenuBar", "com.canonical.dbusmenu", "GetLayout",
                        GLib.Variant("(iias)", (0, -1, [])), "(u(ia{sv}av))").unpack()
    labels = [props.get("label") for _i, props in flatten(layout)]
    assert "Disconnect" in labels and "Connect" not in labels
    tray.close()
