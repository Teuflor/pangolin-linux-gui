"""Unit and integration tests for StatusNotifierItem (SNI) and dbusmenu backend."""
from __future__ import annotations

import os
from pathlib import Path
import struct
import time
import zlib

from gi.repository import Gio, GLib
import pytest

from pangolin_gui.menu_model import (
    CHECK,
    LABEL,
    NORMAL,
    RADIO,
    SEPARATOR,
    MenuNode,
)
from pangolin_gui.sni import (
    SniTray,
    decode_png,
    escape_label,
    node_properties,
    scale_argb,
    sni_available,
)


def make_png_bytes(
    width: int,
    height: int,
    raw_rows: list[tuple[int, bytes]],
    color_type: int = 6,
) -> bytes:
    """Construct a minimal valid PNG in memory with specified scanline filter types."""
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data)
    ihdr_chunk = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)

    stream = bytearray()
    for ftype, row_bytes in raw_rows:
        stream.append(ftype)
        stream.extend(row_bytes)

    compressed = zlib.compress(bytes(stream))
    idat_crc = zlib.crc32(b"IDAT" + compressed)
    idat_chunk = struct.pack(">I", len(compressed)) + b"IDAT" + compressed + struct.pack(">I", idat_crc)

    iend_chunk = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", zlib.crc32(b"IEND"))
    return b"\x89PNG\r\n\x1a\n" + ihdr_chunk + idat_chunk + iend_chunk


# ============================================================================
# Pure Tests
# ============================================================================

def test_escape_label():
    assert escape_label("Connect") == "Connect"
    assert escape_label("Open_Status") == "Open__Status"
    assert escape_label("_File_Open_") == "__File__Open__"
    assert escape_label("") == ""


def test_node_properties():
    # Normal item
    node_norm = MenuNode(id="n1", label="Connect", kind=NORMAL)
    p_norm = node_properties(node_norm)
    assert p_norm["label"].unpack() == "Connect"
    assert "enabled" not in p_norm  # default True omitted
    assert "type" not in p_norm

    # Separator
    node_sep = MenuNode(id="s1", kind=SEPARATOR)
    p_sep = node_properties(node_sep)
    assert p_sep == {"type": GLib.Variant("s", "separator")}

    # Check item (checked)
    node_chk_on = MenuNode(id="c1", label="Auto-Connect", kind=CHECK, checked=True)
    p_chk_on = node_properties(node_chk_on)
    assert p_chk_on["label"].unpack() == "Auto-Connect"
    assert p_chk_on["toggle-type"].unpack() == "checkmark"
    assert p_chk_on["toggle-state"].unpack() == 1

    # Check item (unchecked)
    node_chk_off = MenuNode(id="c2", label="Auto-Connect", kind=CHECK, checked=False)
    p_chk_off = node_properties(node_chk_off)
    assert p_chk_off["toggle-state"].unpack() == 0

    # Radio item
    node_rad = MenuNode(id="r1", label="Option A", kind=RADIO, checked=False)
    p_rad = node_properties(node_rad)
    assert p_rad["label"].unpack() == "Option A"
    assert p_rad["toggle-type"].unpack() == "radio"
    assert p_rad["toggle-state"].unpack() == 0

    # Label (disabled)
    node_lbl = MenuNode(id="l1", label="Status: Active", kind=LABEL)
    p_lbl = node_properties(node_lbl)
    assert p_lbl["label"].unpack() == "Status: Active"
    assert p_lbl["enabled"].unpack() is False

    # Disabled normal item
    node_dis = MenuNode(id="d1", label="Disabled", enabled=False)
    p_dis = node_properties(node_dis)
    assert p_dis["enabled"].unpack() is False

    # Submenu item
    child = MenuNode(id="child1", label="Sub Item")
    node_sub = MenuNode(id="sub1", label="Submenu", children=[child])
    p_sub = node_properties(node_sub)
    assert p_sub["label"].unpack() == "Submenu"
    assert p_sub["children-display"].unpack() == "submenu"

    # Icon name item
    node_icon = MenuNode(id="i1", label="Settings", icon_name="preferences-system")
    p_icon = node_properties(node_icon)
    assert p_icon["icon-name"].unpack() == "preferences-system"


def test_decode_png_filters_and_argb(tmp_path: Path):
    # Construct an image of width=2, height=4 with RGBA (color_type=6)
    # Scanline rows cover filter types 0 (None), 1 (Sub), 2 (Up), 4 (Paeth)
    raw_rows = [
        # Row 0, Filter 0 (None): 2 pixels -> [R, G, B, A]
        (0, bytes([10, 20, 30, 255, 40, 50, 60, 200])),
        # Row 1, Filter 1 (Sub):
        # Raw P10 = [11, 21, 31, 250]; Raw P11 = [16, 26, 36, 255]
        # Diff for P11 is P11 - P10 = [5, 5, 5, 5]
        (1, bytes([11, 21, 31, 250, 5, 5, 5, 5])),
        # Row 2, Filter 2 (Up):
        # Prior is Row 1: [11, 21, 31, 250, 16, 26, 36, 255]
        # Diff is [1, 2, 3, 4, 10, 20, 30, 0]
        # Raw P20 = [12, 23, 34, 254]; Raw P21 = [26, 46, 66, 255]
        (2, bytes([1, 2, 3, 4, 10, 20, 30, 0])),
        # Row 3, Filter 4 (Paeth):
        # Prior is Row 2: P20=[12, 23, 34, 254], P21=[26, 46, 66, 255]
        # Predictor for P30 is P20. Diff = [2, 2, 2, 1] -> Raw P30 = [14, 25, 36, 255]
        # Predictor for P31 is P21. Diff = [3, 4, 5, 0] -> Raw P31 = [29, 50, 71, 255]
        (4, bytes([2, 2, 2, 1, 3, 4, 5, 0])),
    ]

    png_bytes = make_png_bytes(width=2, height=4, raw_rows=raw_rows, color_type=6)

    # Test decoding from in-memory bytes
    w, h, argb = decode_png(png_bytes)
    assert w == 2
    assert h == 4

    # Expected ARGB32 (network byte order: A, R, G, B)
    expected_pixels = [
        # Row 0
        255, 10, 20, 30,
        200, 40, 50, 60,
        # Row 1
        250, 11, 21, 31,
        255, 16, 26, 36,
        # Row 2
        254, 12, 23, 34,
        255, 26, 46, 66,
        # Row 3
        255, 14, 25, 36,
        255, 29, 50, 71,
    ]
    assert argb == bytes(expected_pixels)

    # Test decoding from file path
    png_file = tmp_path / "test.png"
    png_file.write_bytes(png_bytes)
    w_f, h_f, argb_f = decode_png(png_file)
    assert (w_f, h_f, argb_f) == (w, h, argb)


def test_decode_png_rgb_and_average_filter():
    # Test RGB (color_type=2) and Filter 3 (Average)
    # Row 0: Filter 0, pixel [100, 110, 120]
    # Row 1: Filter 3 (Average), Prior is [100, 110, 120], left is 0 -> avg = floor(100/2, 110/2, 120/2) = [50, 55, 60]
    # Diff = [10, 10, 10] -> Raw = [60, 65, 70]
    raw_rows = [
        (0, bytes([100, 110, 120])),
        (3, bytes([10, 10, 10])),
    ]
    png_bytes = make_png_bytes(width=1, height=2, raw_rows=raw_rows, color_type=2)
    w, h, argb = decode_png(png_bytes)
    assert (w, h) == (1, 2)
    # For RGB, alpha must be 255
    expected = bytes([
        255, 100, 110, 120,
        255, 60, 65, 70,
    ])
    assert argb == expected


def test_scale_argb():
    w, h = 4, 4
    dummy_data = bytes(range(w * h * 4))
    # Downscaling to 32x32 and 22x22
    scaled32 = scale_argb(w, h, dummy_data, 32)
    assert len(scaled32) == 32 * 32 * 4

    scaled22 = scale_argb(w, h, dummy_data, 22)
    assert len(scaled22) == 22 * 22 * 4

    # Scaling to original size returns original data
    same = scale_argb(w, h, dummy_data, 4)
    assert same == dummy_data

    # Edge cases
    assert scale_argb(0, 0, b"", 10) == b"\x00" * 400
    assert scale_argb(4, 4, dummy_data, 0) == b""


# ============================================================================
# Private Bus Integration Test
# ============================================================================

WATCHER_INTROSPECTION_XML = """
<node>
  <interface name="org.kde.StatusNotifierWatcher">
    <method name="RegisterStatusNotifierItem">
      <arg name="service" type="s" direction="in"/>
    </method>
  </interface>
</node>
"""


def pump_main_loop(timeout: float = 2.0, condition=lambda: True) -> bool:
    """Run iterations of GLib.MainContext.default() until condition() is True or timeout."""
    context = GLib.MainContext.default()
    start = time.time()
    while time.time() - start < timeout:
        while context.iteration(False):
            pass
        if condition():
            return True
        time.sleep(0.02)
    while context.iteration(False):
        pass
    return condition()


def call_async(conn, *args, timeout: float = 3.0):
    """D-Bus call without blocking the main loop that serves the tray in this same thread.

    (call_sync would deadlock: the reply can only be produced by the loop it blocks.)
    """
    box = {}

    def done(connection, result, _data):
        try:
            box["reply"] = connection.call_finish(result)
        except Exception as exc:  # surfaced below
            box["error"] = exc

    conn.call(*args, done, None)
    assert pump_main_loop(timeout=timeout, condition=lambda: box), "D-Bus call timed out"
    if "error" in box:
        raise box["error"]
    return box["reply"]


def test_sni_tray_integration(tmp_path: Path):
    try:
        test_dbus = Gio.TestDBus.new(Gio.TestDBusFlags.NONE)
        test_dbus.up()
    except Exception as exc:
        pytest.skip(f"Gio.TestDBus could not be started: {exc}")

    try:
        bus_address = test_dbus.get_bus_address()
        conn = Gio.DBusConnection.new_for_address_sync(
            bus_address,
            Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
            None,
            None,
        )

        # 1. Register fake org.kde.StatusNotifierWatcher
        registered_items: list[str] = []

        def on_watcher_method_call(
            connection: Gio.DBusConnection,
            sender: str,
            object_path: str,
            interface_name: str,
            method_name: str,
            parameters: GLib.Variant,
            invocation: Gio.DBusMethodInvocation,
        ) -> None:
            if method_name == "RegisterStatusNotifierItem":
                service = parameters.unpack()[0]
                registered_items.append(service)
                invocation.return_value(None)
            else:
                invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", "")

        watcher_node_info = Gio.DBusNodeInfo.new_for_xml(WATCHER_INTROSPECTION_XML)
        watcher_reg_id = conn.register_object(
            "/StatusNotifierWatcher",
            watcher_node_info.interfaces[0],
            on_watcher_method_call,
            None,
            None,
        )

        watcher_owner_id = Gio.bus_own_name_on_connection(
            conn,
            "org.kde.StatusNotifierWatcher",
            Gio.BusNameOwnerFlags.NONE,
            None,
            None,
        )

        # Confirm sni_available returns True on this bus
        assert pump_main_loop(condition=lambda: sni_available(conn)) is True

        # 2. Write dummy icons to tmp_path
        raw_icon = [(0, bytes([255, 120, 0, 255]))]  # 1x1 orange
        orange_bytes = make_png_bytes(1, 1, raw_icon, 6)
        (tmp_path / "pangolin-orange.png").write_bytes(orange_bytes)

        raw_gray = [(0, bytes([128, 128, 128, 255]))]  # 1x1 gray
        gray_bytes = make_png_bytes(1, 1, raw_gray, 6)
        (tmp_path / "pangolin-gray.png").write_bytes(gray_bytes)

        # 3. Create SniTray
        activated: list[str] = []
        secondary_activated: list[str] = []
        action_clicks: list[str] = []

        tray = SniTray(
            icon_dir=tmp_path,
            on_activate=lambda: activated.append("activate"),
            on_secondary_activate=lambda: secondary_activated.append("secondary"),
            bus=conn,
        )

        # 4. Build menu tree
        nodes = [
            MenuNode(id="item1", label="Action Item", action=lambda: action_clicks.append("clicked")),
            MenuNode(id="sep1", kind=SEPARATOR),
            MenuNode(id="chk1", label="Check Item", kind=CHECK, checked=True),
            MenuNode(id="sub1", label="Submenu", children=[
                MenuNode(id="rad1", label="Radio Item", kind=RADIO, checked=False),
            ]),
        ]
        tray.set_menu(nodes)

        # Wait for watcher to receive registration
        expected_service = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        assert pump_main_loop(condition=lambda: expected_service in registered_items)

        # 5. Connect client connection to inspect and call methods
        conn2 = Gio.DBusConnection.new_for_address_sync(
            bus_address,
            Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
            None,
            None,
        )

        # 6. Verify GetLayout via conn2
        layout_reply = call_async(conn2, 
            expected_service,
            "/MenuBar",
            "com.canonical.dbusmenu",
            "GetLayout",
            GLib.Variant("(iias)", (0, -1, [])),
            GLib.VariantType("(u(ia{sv}av))"),
            Gio.DBusCallFlags.NONE,
            2000,
            None,
        )
        rev, layout = layout_reply.unpack()
        assert rev >= 1
        root_id, root_props, children = layout
        assert root_id == 0
        assert len(children) == 4

        # Verify child items
        c0_id, c0_props, _ = children[0]
        assert c0_props["label"] == "Action Item"

        c1_id, c1_props, _ = children[1]
        assert c1_props["type"] == "separator"

        c2_id, c2_props, _ = children[2]
        assert c2_props["label"] == "Check Item"
        assert c2_props["toggle-type"] == "checkmark"
        assert c2_props["toggle-state"] == 1

        c3_id, c3_props, c3_children = children[3]
        assert c3_props["label"] == "Submenu"
        assert c3_props["children-display"] == "submenu"
        assert len(c3_children) == 1
        c3_sub_id, c3_sub_props, _ = c3_children[0]
        assert c3_sub_props["label"] == "Radio Item"
        assert c3_sub_props["toggle-type"] == "radio"
        assert c3_sub_props["toggle-state"] == 0

        # 7. Event(id, "clicked") executes action
        call_async(conn2, 
            expected_service,
            "/MenuBar",
            "com.canonical.dbusmenu",
            "Event",
            GLib.Variant("(isvu)", (c0_id, "clicked", GLib.Variant("s", ""), 0)),
            None,
            Gio.DBusCallFlags.NONE,
            2000,
            None,
        )
        assert pump_main_loop(condition=lambda: action_clicks == ["clicked"])

        # 8. Activate(0, 0) calls on_activate
        call_async(conn2, 
            expected_service,
            "/StatusNotifierItem",
            "org.kde.StatusNotifierItem",
            "Activate",
            GLib.Variant("(ii)", (0, 0)),
            None,
            Gio.DBusCallFlags.NONE,
            2000,
            None,
        )
        assert pump_main_loop(condition=lambda: activated == ["activate"])

        # 9. SecondaryActivate(0, 0) calls on_secondary_activate
        call_async(conn2, 
            expected_service,
            "/StatusNotifierItem",
            "org.kde.StatusNotifierItem",
            "SecondaryActivate",
            GLib.Variant("(ii)", (0, 0)),
            None,
            Gio.DBusCallFlags.NONE,
            2000,
            None,
        )
        assert pump_main_loop(condition=lambda: secondary_activated == ["secondary"])

        # 10. set_icon(True) -> reading IconName property gives "pangolin-orange"
        tray.set_icon(True)
        pump_main_loop(timeout=0.1)

        prop_reply = call_async(conn2, 
            expected_service,
            "/StatusNotifierItem",
            "org.freedesktop.DBus.Properties",
            "Get",
            GLib.Variant("(ss)", ("org.kde.StatusNotifierItem", "IconName")),
            GLib.VariantType("(v)"),
            Gio.DBusCallFlags.NONE,
            2000,
            None,
        )
        assert prop_reply.unpack()[0] == "pangolin-orange"

        # 11. set_menu with a changed label emits LayoutUpdated with a higher revision
        # while keeping the int id of an unchanged string id
        saved_c0_id = c0_id
        saved_rev = rev

        renamed_nodes = [
            MenuNode(id="item1", label="Action Item", action=lambda: action_clicks.append("clicked")),
            MenuNode(id="sep1", kind=SEPARATOR),
            MenuNode(id="chk1", label="Check Item Renamed", kind=CHECK, checked=True),
            MenuNode(id="sub1", label="Submenu", children=[
                MenuNode(id="rad1", label="Radio Item", kind=RADIO, checked=False),
            ]),
        ]
        tray.set_menu(renamed_nodes)

        updated_reply = call_async(conn2, 
            expected_service,
            "/MenuBar",
            "com.canonical.dbusmenu",
            "GetLayout",
            GLib.Variant("(iias)", (0, -1, [])),
            GLib.VariantType("(u(ia{sv}av))"),
            Gio.DBusCallFlags.NONE,
            2000,
            None,
        )
        new_rev, new_layout = updated_reply.unpack()
        assert new_rev > saved_rev

        new_children = new_layout[2]
        new_c0_id = new_children[0][0]
        assert new_c0_id == saved_c0_id
        assert new_children[2][1]["label"] == "Check Item Renamed"

        # 12. Teardown
        tray.close()
        conn.unregister_object(watcher_reg_id)
        Gio.bus_unown_name(watcher_owner_id)
        conn2.close_sync(None)
        conn.close_sync(None)

    finally:
        test_dbus.down()
