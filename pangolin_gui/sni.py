"""StatusNotifierItem (SNI) and com.canonical.dbusmenu tray backend for Pangolin.

Implements the TrayBackend protocol over D-Bus using PyGObject Gio and GLib without
depending on GTK or external Python D-Bus libraries.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
import struct
from typing import BinaryIO, Callable
import zlib

from gi.repository import Gio, GLib

from pangolin_gui.menu_model import (
    CHECK,
    LABEL,
    RADIO,
    SEPARATOR,
    MenuNode,
    signature,
    walk,
)

log = logging.getLogger(__name__)

SNI_INTROSPECTION_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="i" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconPixmap" type="a(iiay)" access="read"/>
    <property name="OverlayIconName" type="s" access="read"/>
    <property name="OverlayIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="AttentionIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionMovieName" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>

    <method name="ContextMenu">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="Activate">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="SecondaryActivate">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="Scroll">
      <arg name="delta" type="i" direction="in"/>
      <arg name="orientation" type="s" direction="in"/>
    </method>

    <signal name="NewTitle"/>
    <signal name="NewIcon"/>
    <signal name="NewAttentionIcon"/>
    <signal name="NewOverlayIcon"/>
    <signal name="NewToolTip"/>
    <signal name="NewStatus">
      <arg name="status" type="s"/>
    </signal>
  </interface>
</node>
"""

DBUSMENU_INTROSPECTION_XML = """
<node>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>

    <method name="GetLayout">
      <arg name="parentId" type="i" direction="in"/>
      <arg name="recursionDepth" type="i" direction="in"/>
      <arg name="propertyNames" type="as" direction="in"/>
      <arg name="revision" type="u" direction="out"/>
      <arg name="layout" type="(ia{sv}av)" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg name="ids" type="ai" direction="in"/>
      <arg name="propertyNames" type="as" direction="in"/>
      <arg name="properties" type="a(ia{sv})" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg name="id" type="i" direction="in"/>
      <arg name="name" type="s" direction="in"/>
      <arg name="value" type="v" direction="out"/>
    </method>
    <method name="Event">
      <arg name="id" type="i" direction="in"/>
      <arg name="eventId" type="s" direction="in"/>
      <arg name="data" type="v" direction="in"/>
      <arg name="timestamp" type="u" direction="in"/>
    </method>
    <method name="EventGroup">
      <arg name="events" type="a(isvu)" direction="in"/>
      <arg name="idErrors" type="ai" direction="out"/>
    </method>
    <method name="AboutToShow">
      <arg name="id" type="i" direction="in"/>
      <arg name="needUpdate" type="b" direction="out"/>
    </method>
    <method name="AboutToShowGroup">
      <arg name="ids" type="ai" direction="in"/>
      <arg name="updatesNeeded" type="ai" direction="out"/>
      <arg name="idErrors" type="ai" direction="out"/>
    </method>

    <signal name="ItemsPropertiesUpdated">
      <arg name="updated" type="a(ia{sv})"/>
      <arg name="removed" type="a(ias)"/>
    </signal>
    <signal name="LayoutUpdated">
      <arg name="revision" type="u"/>
      <arg name="parent" type="i"/>
    </signal>
    <signal name="ItemActivationRequested">
      <arg name="id" type="i"/>
      <arg name="timestamp" type="u"/>
    </signal>
  </interface>
</node>
"""


# ---------------------------------------------------------------------------
# Pure Helper Functions
# ---------------------------------------------------------------------------

def escape_label(label: str) -> str:
    """Escape '_' as '__' because dbusmenu uses '_' for accelerators/mnemonics."""
    return label.replace("_", "__")


def node_properties(node: MenuNode) -> dict[str, GLib.Variant]:
    """Return non-default com.canonical.dbusmenu properties for a MenuNode."""
    if node.kind == SEPARATOR:
        return {"type": GLib.Variant("s", "separator")}

    props: dict[str, GLib.Variant] = {}

    if node.label:
        props["label"] = GLib.Variant("s", escape_label(node.label))

    if node.kind == LABEL or not node.enabled:
        props["enabled"] = GLib.Variant("b", False)

    if node.kind == CHECK:
        props["toggle-type"] = GLib.Variant("s", "checkmark")
        props["toggle-state"] = GLib.Variant("i", 1 if node.checked else 0)
    elif node.kind == RADIO:
        props["toggle-type"] = GLib.Variant("s", "radio")
        props["toggle-state"] = GLib.Variant("i", 1 if node.checked else 0)

    if node.children:
        props["children-display"] = GLib.Variant("s", "submenu")

    if node.icon_name:
        props["icon-name"] = GLib.Variant("s", node.icon_name)

    return props


def decode_png(path: str | Path | bytes | BinaryIO) -> tuple[int, int, bytes]:
    """Decode an 8-bit PNG into (width, height, argb_bytes).

    Supports 8-bit RGBA (color type 6) and 8-bit RGB (color type 2), non-interlaced,
    all 5 PNG filter types (0: None, 1: Sub, 2: Up, 3: Average, 4: Paeth).
    Output bytes are in network byte order ARGB32 (bytes A, R, G, B per pixel).
    """
    if isinstance(path, (bytes, bytearray)):
        data = bytes(path)
    elif hasattr(path, "read"):
        data = path.read()
    else:
        with open(path, "rb") as f:
            data = f.read()

    if len(data) < 8 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Invalid PNG signature")

    pos = 8
    idat_chunks: list[bytes] = []
    ihdr_found = False
    width = 0
    height = 0
    bit_depth = 0
    color_type = 0

    while pos + 8 <= len(data):
        length, chunk_type = struct.unpack(">I4s", data[pos : pos + 8])
        pos += 8
        if pos + length + 4 > len(data):
            raise ValueError("Truncated PNG chunk")
        chunk_data = data[pos : pos + length]
        pos += length + 4  # skip CRC

        if chunk_type == b"IHDR":
            if ihdr_found:
                raise ValueError("Duplicate IHDR chunk")
            if length != 13:
                raise ValueError(f"Invalid IHDR length: {length}")
            width, height, bit_depth, color_type, comp, filt, interlace = struct.unpack(
                ">IIBBBBB", chunk_data
            )
            if bit_depth != 8:
                raise ValueError(f"Unsupported PNG bit depth: {bit_depth}")
            if color_type not in (2, 6):
                raise ValueError(f"Unsupported PNG color type: {color_type}")
            if comp != 0 or filt != 0:
                raise ValueError("Unsupported PNG compression or filter method")
            if interlace != 0:
                raise ValueError("Interlaced PNGs are not supported")
            ihdr_found = True
        elif chunk_type == b"IDAT":
            if not ihdr_found:
                raise ValueError("IDAT chunk appeared before IHDR")
            idat_chunks.append(chunk_data)
        elif chunk_type == b"IEND":
            break

    if not ihdr_found:
        raise ValueError("Missing IHDR chunk in PNG")
    if not idat_chunks:
        raise ValueError("Missing IDAT chunks in PNG")

    decompressed = zlib.decompress(b"".join(idat_chunks))
    bpp = 4 if color_type == 6 else 3
    stride = width * bpp
    expected_size = height * (1 + stride)
    if len(decompressed) < expected_size:
        raise ValueError(f"Decompressed PNG data truncated: {len(decompressed)} < {expected_size}")

    raw_bytes = bytearray(width * height * bpp)
    prior = bytearray(stride)
    in_pos = 0
    out_pos = 0

    for _ in range(height):
        filter_type = decompressed[in_pos]
        in_pos += 1
        scanline = bytearray(decompressed[in_pos : in_pos + stride])
        in_pos += stride

        if filter_type == 0:  # None
            pass
        elif filter_type == 1:  # Sub
            for x in range(bpp, stride):
                scanline[x] = (scanline[x] + scanline[x - bpp]) & 0xFF
        elif filter_type == 2:  # Up
            for x in range(stride):
                scanline[x] = (scanline[x] + prior[x]) & 0xFF
        elif filter_type == 3:  # Average
            for x in range(stride):
                left = scanline[x - bpp] if x >= bpp else 0
                up = prior[x]
                scanline[x] = (scanline[x] + ((left + up) >> 1)) & 0xFF
        elif filter_type == 4:  # Paeth
            for x in range(stride):
                a = scanline[x - bpp] if x >= bpp else 0
                b = prior[x]
                c = prior[x - bpp] if x >= bpp else 0
                p = a + b - c
                pa = abs(p - a)
                pb = abs(p - b)
                pc = abs(p - c)
                if pa <= pb and pa <= pc:
                    pr = a
                elif pb <= pc:
                    pr = b
                else:
                    pr = c
                scanline[x] = (scanline[x] + pr) & 0xFF
        else:
            raise ValueError(f"Unknown PNG filter type: {filter_type}")

        prior = scanline
        raw_bytes[out_pos : out_pos + stride] = scanline
        out_pos += stride

    num_pixels = width * height
    argb = bytearray(num_pixels * 4)

    if color_type == 6:  # RGBA -> ARGB32
        argb[0::4] = raw_bytes[3::4]  # Alpha
        argb[1::4] = raw_bytes[0::4]  # Red
        argb[2::4] = raw_bytes[1::4]  # Green
        argb[3::4] = raw_bytes[2::4]  # Blue
    else:  # RGB -> ARGB32
        argb[0::4] = b"\xff" * num_pixels  # Alpha (opaque)
        argb[1::4] = raw_bytes[0::3]       # Red
        argb[2::4] = raw_bytes[1::3]       # Green
        argb[3::4] = raw_bytes[2::3]       # Blue

    return width, height, bytes(argb)


def scale_argb(w: int, h: int, data: bytes, size: int) -> bytes:
    """Scale an ARGB byte buffer to size x size using nearest-neighbor sampling."""
    if size <= 0:
        return b""
    if w <= 0 or h <= 0 or len(data) < w * h * 4:
        return b"\x00" * (size * size * 4)
    if w == size and h == size:
        return bytes(data[: size * size * 4])

    out = bytearray(size * size * 4)
    x_offsets = [min(int(x * w / size), w - 1) * 4 for x in range(size)]
    row_stride = w * 4
    out_idx = 0

    for y in range(size):
        src_y = min(int(y * h / size), h - 1)
        row_start = src_y * row_stride
        for x in range(size):
            src_pos = row_start + x_offsets[x]
            out[out_idx : out_idx + 4] = data[src_pos : src_pos + 4]
            out_idx += 4

    return bytes(out)


def sni_available(bus: Gio.DBusConnection | None = None) -> bool:
    """True if org.kde.StatusNotifierWatcher has an owner on the bus; False on any error."""
    try:
        if bus is None:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        reply = bus.call_sync(
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "NameHasOwner",
            GLib.Variant("(s)", ("org.kde.StatusNotifierWatcher",)),
            GLib.VariantType("(b)"),
            Gio.DBusCallFlags.NONE,
            1000,
            None,
        )
        return bool(reply.unpack()[0])
    except Exception:
        return False


# ---------------------------------------------------------------------------
# dbusmenu Exporter
# ---------------------------------------------------------------------------

class DbusMenu:
    """Exports com.canonical.dbusmenu at /MenuBar over D-Bus."""

    def __init__(
        self,
        bus: Gio.DBusConnection,
        object_path: str = "/MenuBar",
        icon_dir: Path | None = None,
    ) -> None:
        self.bus = bus
        self.object_path = object_path
        self.icon_dir = Path(icon_dir) if icon_dir else None
        self._revision = 1
        self._last_signature: tuple | None = None

        self._str_to_int: dict[str, int] = {}
        self._next_id: int = 1
        self._id_to_node: dict[int, MenuNode] = {}
        self._root_children: list[int] = []

        node_info = Gio.DBusNodeInfo.new_for_xml(DBUSMENU_INTROSPECTION_XML)
        self._iface_info = node_info.interfaces[0]

        self._reg_id = self.bus.register_object(
            self.object_path,
            self._iface_info,
            self._on_method_call,
            self._on_get_property,
            None,
        )

    def _on_get_property(
        self,
        connection: Gio.DBusConnection,
        sender: str,
        object_path: str,
        interface_name: str,
        property_name: str,
    ) -> GLib.Variant | None:
        if property_name == "Version":
            return GLib.Variant("u", 3)
        if property_name == "TextDirection":
            return GLib.Variant("s", "ltr")
        if property_name == "Status":
            return GLib.Variant("s", "normal")
        if property_name == "IconThemePath":
            paths = [str(self.icon_dir)] if self.icon_dir else []
            return GLib.Variant("as", paths)
        return None

    def _on_method_call(
        self,
        connection: Gio.DBusConnection,
        sender: str,
        object_path: str,
        interface_name: str,
        method_name: str,
        parameters: GLib.Variant,
        invocation: Gio.DBusMethodInvocation,
    ) -> None:
        if method_name == "GetLayout":
            parent_id, recursion_depth, property_names = parameters.unpack()
            self._handle_get_layout(parent_id, recursion_depth, property_names, invocation)
        elif method_name == "GetGroupProperties":
            ids, property_names = parameters.unpack()
            self._handle_get_group_properties(ids, property_names, invocation)
        elif method_name == "GetProperty":
            item_id, prop_name = parameters.unpack()
            self._handle_get_property(item_id, prop_name, invocation)
        elif method_name == "Event":
            item_id, event_id, data, timestamp = parameters.unpack()
            self._handle_event(item_id, event_id, data, timestamp, invocation)
        elif method_name == "EventGroup":
            events = parameters.unpack()[0]
            self._handle_event_group(events, invocation)
        elif method_name == "AboutToShow":
            invocation.return_value(GLib.Variant("(b)", (False,)))
        elif method_name == "AboutToShowGroup":
            invocation.return_value(GLib.Variant("(aiai)", ([], [])))
        else:
            invocation.return_dbus_error(
                "org.freedesktop.DBus.Error.UnknownMethod",
                f"Unknown method {method_name}",
            )

    def _get_root_properties(self) -> dict[str, GLib.Variant]:
        if self._root_children:
            return {"children-display": GLib.Variant("s", "submenu")}
        return {}

    def _handle_get_layout(
        self,
        parent_id: int,
        recursion_depth: int,
        property_names: list[str],
        invocation: Gio.DBusMethodInvocation,
    ) -> None:
        if parent_id == 0:
            root_props = self._get_root_properties()
            if property_names:
                root_props = {k: v for k, v in root_props.items() if k in property_names}

            if recursion_depth == 0:
                children_variants = []
            else:
                next_depth = recursion_depth - 1 if recursion_depth > 0 else -1
                children_variants = [
                    GLib.Variant.new_variant(
                        self._build_node_layout(child_id, next_depth, property_names)
                    )
                    for child_id in self._root_children
                ]

            node_id_var = GLib.Variant.new_int32(0)
            props_var = GLib.Variant("a{sv}", root_props)
            children_var = GLib.Variant("av", children_variants)
            layout = GLib.Variant.new_tuple(node_id_var, props_var, children_var)
        elif parent_id in self._id_to_node:
            layout = self._build_node_layout(parent_id, recursion_depth, property_names)
        else:
            invocation.return_dbus_error(
                "com.canonical.dbusmenu.Error.UnknownId",
                f"Unknown parent id {parent_id}",
            )
            return

        reply = GLib.Variant.new_tuple(GLib.Variant.new_uint32(self._revision), layout)
        invocation.return_value(reply)

    def _build_node_layout(
        self,
        node_id: int,
        depth: int,
        property_names: list[str],
    ) -> GLib.Variant:
        node = self._id_to_node[node_id]
        props = node_properties(node)
        if property_names:
            props = {k: v for k, v in props.items() if k in property_names}

        if depth == 0 or not node.children:
            children_variants = []
        else:
            next_depth = depth - 1 if depth > 0 else -1
            children_variants = [
                GLib.Variant.new_variant(
                    self._build_node_layout(self._str_to_int[child.id], next_depth, property_names)
                )
                for child in node.children
            ]

        node_id_var = GLib.Variant.new_int32(node_id)
        props_var = GLib.Variant("a{sv}", props)
        children_var = GLib.Variant("av", children_variants)
        return GLib.Variant.new_tuple(node_id_var, props_var, children_var)

    def _handle_get_group_properties(
        self,
        ids: list[int],
        property_names: list[str],
        invocation: Gio.DBusMethodInvocation,
    ) -> None:
        result = []
        for item_id in ids:
            if item_id == 0:
                props = self._get_root_properties()
            elif item_id in self._id_to_node:
                props = node_properties(self._id_to_node[item_id])
            else:
                continue

            if property_names:
                props = {k: v for k, v in props.items() if k in property_names}
            result.append((item_id, props))

        invocation.return_value(GLib.Variant("(a(ia{sv}))", (result,)))

    def _handle_get_property(
        self,
        item_id: int,
        prop_name: str,
        invocation: Gio.DBusMethodInvocation,
    ) -> None:
        if item_id == 0:
            props = self._get_root_properties()
        elif item_id in self._id_to_node:
            props = node_properties(self._id_to_node[item_id])
        else:
            props = {}

        if prop_name in props:
            invocation.return_value(GLib.Variant("(v)", (props[prop_name],)))
        else:
            invocation.return_dbus_error(
                "com.canonical.dbusmenu.Error.UnknownProperty",
                f"Property {prop_name} not found",
            )

    def _handle_event(
        self,
        item_id: int,
        event_id: str,
        data: GLib.Variant,
        timestamp: int,
        invocation: Gio.DBusMethodInvocation,
    ) -> None:
        if item_id in self._id_to_node:
            node = self._id_to_node[item_id]
            if event_id == "clicked" and node.action is not None:
                action = node.action

                def _run_action() -> bool:
                    try:
                        action()
                    except Exception as exc:
                        log.exception("Error executing menu action for %r: %s", node.id, exc)
                    return False

                GLib.idle_add(_run_action)
        invocation.return_value(None)

    def _handle_event_group(
        self,
        events: list[tuple[int, str, GLib.Variant, int]],
        invocation: Gio.DBusMethodInvocation,
    ) -> None:
        id_errors = []
        for item_id, event_id, data, timestamp in events:
            if item_id in self._id_to_node:
                node = self._id_to_node[item_id]
                if event_id == "clicked" and node.action is not None:
                    action = node.action

                    def _run(act=action) -> bool:
                        try:
                            act()
                        except Exception as exc:
                            log.exception("Error executing menu action: %s", exc)
                        return False

                    GLib.idle_add(_run)
            else:
                id_errors.append(item_id)
        invocation.return_value(GLib.Variant("(ai)", (id_errors,)))

    def set_menu(self, nodes: list[MenuNode]) -> None:
        for node in walk(nodes):
            if node.id not in self._str_to_int:
                self._str_to_int[node.id] = self._next_id
                self._next_id += 1

        self._id_to_node = {self._str_to_int[n.id]: n for n in walk(nodes)}
        self._root_children = [self._str_to_int[n.id] for n in nodes]

        sig = signature(nodes)
        if self._last_signature is not None and sig == self._last_signature:
            return
        self._last_signature = sig
        self._revision += 1
        try:
            self.bus.emit_signal(
                None,
                self.object_path,
                "com.canonical.dbusmenu",
                "LayoutUpdated",
                GLib.Variant("(ui)", (self._revision, 0)),
            )
        except Exception as exc:
            log.warning("Could not emit LayoutUpdated: %s", exc)

    def close(self) -> None:
        if self._reg_id is not None:
            try:
                self.bus.unregister_object(self._reg_id)
            except Exception:
                pass
            self._reg_id = None


# ---------------------------------------------------------------------------
# StatusNotifierItem Tray Backend
# ---------------------------------------------------------------------------

class SniTray:
    """StatusNotifierItem backend exporting org.kde.StatusNotifierItem over D-Bus."""

    def __init__(
        self,
        icon_dir: Path,
        on_activate: Callable[[], None],
        on_secondary_activate: Callable[[], None] | None = None,
        item_id: str = "pangolin-gui",
        title: str = "Pangolin",
        bus: Gio.DBusConnection | None = None,
    ) -> None:
        self.icon_dir = Path(icon_dir)
        self.on_activate = on_activate
        self.on_secondary_activate = on_secondary_activate
        self.item_id = item_id
        self.title = title

        if bus is None:
            self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        else:
            self.bus = bus

        self._service_name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        self._object_path = "/StatusNotifierItem"
        self._closed = False
        self._name_acquired = False

        self._icon_name: str = "network-vpn"
        self._icon_pixmaps: list[tuple[int, int, bytes]] = []
        self._icon_cache: dict[tuple[str, int], list[tuple[int, int, bytes]]] = {}

        self._tooltip_title: str = title
        self._tooltip_text: str = ""

        # Export com.canonical.dbusmenu on /MenuBar
        self._dbus_menu = DbusMenu(self.bus, "/MenuBar", self.icon_dir)

        # Export org.kde.StatusNotifierItem on /StatusNotifierItem
        node_info = Gio.DBusNodeInfo.new_for_xml(SNI_INTROSPECTION_XML)
        self._sni_iface_info = node_info.interfaces[0]
        self._sni_reg_id = self.bus.register_object(
            self._object_path,
            self._sni_iface_info,
            self._on_method_call,
            self._on_get_property,
            None,
        )

        # Apply initial icon (disconnected / gray)
        self.set_icon(False)

        # Own bus name
        self._owner_id = Gio.bus_own_name_on_connection(
            self.bus,
            self._service_name,
            Gio.BusNameOwnerFlags.NONE,
            self._on_name_acquired,
            self._on_name_lost,
        )

        # Watch StatusNotifierWatcher
        self._watcher_id = Gio.bus_watch_name_on_connection(
            self.bus,
            "org.kde.StatusNotifierWatcher",
            Gio.BusNameWatcherFlags.NONE,
            self._on_watcher_appeared,
            self._on_watcher_vanished,
        )

        # Registration happens once the bus name is ours (_on_name_acquired).

    def _on_get_property(
        self,
        connection: Gio.DBusConnection,
        sender: str,
        object_path: str,
        interface_name: str,
        property_name: str,
    ) -> GLib.Variant | None:
        if property_name == "Category":
            return GLib.Variant("s", "ApplicationStatus")
        if property_name == "Id":
            return GLib.Variant("s", self.item_id)
        if property_name == "Title":
            return GLib.Variant("s", self.title)
        if property_name == "Status":
            return GLib.Variant("s", "Active")
        if property_name == "WindowId":
            return GLib.Variant("i", 0)
        if property_name == "IconThemePath":
            return GLib.Variant("s", str(self.icon_dir))
        if property_name == "ItemIsMenu":
            return GLib.Variant("b", False)
        if property_name == "Menu":
            return GLib.Variant("o", "/MenuBar")
        if property_name == "IconName":
            return GLib.Variant("s", self._icon_name)
        if property_name == "IconPixmap":
            return GLib.Variant("a(iiay)", [(w, h, data) for w, h, data in self._icon_pixmaps])
        if property_name == "OverlayIconName":
            return GLib.Variant("s", "")
        if property_name == "OverlayIconPixmap":
            return GLib.Variant("a(iiay)", [])
        if property_name == "AttentionIconName":
            return GLib.Variant("s", "")
        if property_name == "AttentionIconPixmap":
            return GLib.Variant("a(iiay)", [])
        if property_name == "AttentionMovieName":
            return GLib.Variant("s", "")
        if property_name == "ToolTip":
            return GLib.Variant(
                "(sa(iiay)ss)",
                ("", [], self._tooltip_title, self._tooltip_text),
            )
        return None

    def _on_method_call(
        self,
        connection: Gio.DBusConnection,
        sender: str,
        object_path: str,
        interface_name: str,
        method_name: str,
        parameters: GLib.Variant,
        invocation: Gio.DBusMethodInvocation,
    ) -> None:
        if method_name == "Activate":
            if self.on_activate:
                def _run_act() -> bool:
                    try:
                        self.on_activate()
                    except Exception as exc:
                        log.exception("Error in on_activate: %s", exc)
                    return False

                GLib.idle_add(_run_act)
            invocation.return_value(None)
        elif method_name == "SecondaryActivate":
            if self.on_secondary_activate:
                def _run_sec() -> bool:
                    try:
                        self.on_secondary_activate()
                    except Exception as exc:
                        log.exception("Error in on_secondary_activate: %s", exc)
                    return False

                GLib.idle_add(_run_sec)
            invocation.return_value(None)
        elif method_name in ("ContextMenu", "Scroll"):
            invocation.return_value(None)
        else:
            invocation.return_dbus_error(
                "org.freedesktop.DBus.Error.UnknownMethod",
                f"Unknown method {method_name}",
            )

    def _emit_signal(self, name: str, parameters: GLib.Variant | None = None) -> None:
        if self._closed:
            return
        try:
            self.bus.emit_signal(
                None,
                self._object_path,
                "org.kde.StatusNotifierItem",
                name,
                parameters,
            )
        except Exception as exc:
            log.warning("Could not emit signal %s: %s", name, exc)

    def _register(self) -> None:
        if self._closed:
            return
        try:
            self.bus.call(
                "org.kde.StatusNotifierWatcher",
                "/StatusNotifierWatcher",
                "org.kde.StatusNotifierWatcher",
                "RegisterStatusNotifierItem",
                GLib.Variant("(s)", (self._service_name,)),
                None,
                Gio.DBusCallFlags.NONE,
                -1,
                None,
                self._on_register_reply,
            )
        except Exception as exc:
            log.info("StatusNotifierWatcher registration failed to send: %s", exc)

    def _on_register_reply(self, conn: Gio.DBusConnection, result: Gio.AsyncResult) -> None:
        try:
            conn.call_finish(result)
            log.info("Registered %s with StatusNotifierWatcher", self._service_name)
        except Exception as exc:
            log.info("StatusNotifierWatcher registration not acknowledged: %s", exc)

    def _on_watcher_appeared(self, conn: Gio.DBusConnection, name: str, name_owner: str) -> None:
        log.info("StatusNotifierWatcher appeared (%s)", name_owner)
        if self._name_acquired:  # otherwise _on_name_acquired registers
            self._register()

    def _on_watcher_vanished(self, conn: Gio.DBusConnection, name: str) -> None:
        log.info("StatusNotifierWatcher vanished")

    def _on_name_acquired(self, conn: Gio.DBusConnection, name: str) -> None:
        log.info("Acquired D-Bus name %s", name)
        self._name_acquired = True
        self._register()

    def _on_name_lost(self, conn: Gio.DBusConnection, name: str) -> None:
        log.info("Lost D-Bus name %s", name)

    # -----------------------------------------------------------------------
    # TrayBackend Protocol Methods
    # -----------------------------------------------------------------------

    def set_menu(self, nodes: list[MenuNode]) -> None:
        if self._dbus_menu is not None:
            self._dbus_menu.set_menu(nodes)

    def set_icon(self, connected: bool) -> None:
        filename = "pangolin-orange.png" if connected else "pangolin-gray.png"
        icon_path = self.icon_dir / filename

        pixmaps: list[tuple[int, int, bytes]] = []
        icon_name = "network-vpn"

        if icon_path.is_file():
            try:
                mtime = icon_path.stat().st_mtime_ns
            except OSError:
                mtime = 0
            cache_key = (str(icon_path), mtime)

            if cache_key in self._icon_cache:
                pixmaps = self._icon_cache[cache_key]
                icon_name = icon_path.stem
            else:
                try:
                    w, h, argb = decode_png(icon_path)
                    pixmaps = [(w, h, argb)]
                    if (w, h) != (32, 32):
                        pixmaps.append((32, 32, scale_argb(w, h, argb, 32)))
                    if (w, h) != (22, 22):
                        pixmaps.append((22, 22, scale_argb(w, h, argb, 22)))
                    self._icon_cache[cache_key] = pixmaps
                    icon_name = icon_path.stem
                except Exception as exc:
                    log.warning("Could not decode icon %s: %s", icon_path, exc)
                    pixmaps = []
                    icon_name = "network-vpn"
        else:
            pixmaps = []
            icon_name = "network-vpn"

        changed = (self._icon_name != icon_name or self._icon_pixmaps != pixmaps)
        self._icon_name = icon_name
        self._icon_pixmaps = pixmaps

        if changed:
            self._emit_signal("NewIcon")

    def set_tooltip(self, title: str, text: str) -> None:
        changed = (self._tooltip_title != title or self._tooltip_text != text)
        self._tooltip_title = title
        self._tooltip_text = text
        if changed:
            self._emit_signal("NewToolTip")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True

        if self._watcher_id is not None:
            try:
                Gio.bus_unwatch_name(self._watcher_id)
            except Exception:
                pass
            self._watcher_id = None

        if self._owner_id is not None:
            try:
                Gio.bus_unown_name(self._owner_id)
            except Exception:
                pass
            self._owner_id = None

        if self._sni_reg_id is not None:
            try:
                self.bus.unregister_object(self._sni_reg_id)
            except Exception:
                pass
            self._sni_reg_id = None

        if self._dbus_menu is not None:
            try:
                self._dbus_menu.close()
            except Exception:
                pass
            self._dbus_menu = None
