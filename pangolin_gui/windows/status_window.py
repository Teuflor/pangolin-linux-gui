"""Status window: connection summary and per-site peer table."""
from __future__ import annotations

import re
from datetime import datetime, timezone

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from pangolin_gui.models import AppState, ConnState  # noqa: E402

_DOT = {
    ConnState.CONNECTED: ("#22c55e", "Connected"),
    ConnState.CONNECTING: ("#f97316", "Connecting…"),
    ConnState.DISCONNECTING: ("#9ca3af", "Disconnecting…"),
    ConnState.DISCONNECTED: ("#9ca3af", "Disconnected"),
    ConnState.ERROR: ("#ef4444", "Error"),
}


def format_relative(iso: str | None, now: datetime | None = None) -> str:
    """Format an ISO-8601 timestamp as a short relative time."""
    if not iso:
        return "–"
    try:
        text = iso.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        text = re.sub(r"(\.\d{6})\d+", r"\1", text)  # Go emits nanoseconds
        dt = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return "–"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    seconds = int((now - dt).total_seconds())
    if seconds < 5:
        return "just now"
    if seconds < 60:
        return f"{seconds} s ago"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    if seconds < 86400:
        return f"{seconds // 3600} h ago"
    return f"{seconds // 86400} d ago"


def org_display_name(state: AppState) -> str:
    org_id = (state.status.org_id if state.status else "") or (
        state.active_account.org_id if state.active_account else "")
    if not org_id:
        return "–"
    for org in state.orgs:
        if org.org_id == org_id:
            return org.name
    return org_id


class StatusWindow(Gtk.Window):
    # ListStore columns
    COL_ID, COL_NAME, COL_STATUS, COL_CONN, COL_ENDPOINT, COL_IP, COL_RTT_TEXT, COL_SEEN, COL_RTT = range(9)

    def __init__(self, controller):
        super().__init__(title="Pangolin Status")
        self.controller = controller
        self._conn = ConnState.DISCONNECTED
        self.set_default_size(640, 420)
        self.set_icon_name("network-vpn")
        self.connect("delete-event", self._on_delete)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, border_width=12)
        self.add(root)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        root.pack_start(header, False, False, 0)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        header.pack_start(left, True, True, 0)
        self.status_label = Gtk.Label(xalign=0)
        left.pack_start(self.status_label, False, False, 0)

        grid = Gtk.Grid(column_spacing=12, row_spacing=4)
        left.pack_start(grid, False, False, 0)
        self._values = {}
        for row, key in enumerate(("Account", "Organization", "Version", "Exit node")):
            name = Gtk.Label(label=key, xalign=0)
            name.get_style_context().add_class("dim-label")
            value = Gtk.Label(xalign=0, selectable=True)
            grid.attach(name, 0, row, 1, 1)
            grid.attach(value, 1, row, 1, 1)
            self._values[key] = value

        self.action_button = Gtk.Button(label="Connect", valign=Gtk.Align.START)
        self.action_button.connect("clicked", self._on_action)
        header.pack_end(self.action_button, False, False, 0)

        self.info_bar = Gtk.InfoBar(message_type=Gtk.MessageType.ERROR)
        self.info_label = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.info_bar.get_content_area().add(self.info_label)
        self.info_bar.set_no_show_all(True)
        root.pack_start(self.info_bar, False, False, 0)

        self.store = Gtk.ListStore(int, str, str, str, str, str, str, str, float)
        self.tree = Gtk.TreeView(model=self.store)
        columns = [("Site", self.COL_NAME, self.COL_NAME), ("Status", self.COL_STATUS, self.COL_STATUS),
                   ("Connection", self.COL_CONN, self.COL_CONN), ("Endpoint", self.COL_ENDPOINT, self.COL_ENDPOINT),
                   ("Peer IP", self.COL_IP, self.COL_IP), ("RTT", self.COL_RTT_TEXT, self.COL_RTT),
                   ("Last seen", self.COL_SEEN, self.COL_SEEN)]
        for title, text_col, sort_col in columns:
            col = Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=text_col)
            col.set_sort_column_id(sort_col)
            col.set_resizable(True)
            self.tree.append_column(col)
        self.store.set_sort_column_id(self.COL_NAME, Gtk.SortType.ASCENDING)

        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_shadow_type(Gtk.ShadowType.IN)
        scroller.add(self.tree)
        root.pack_start(scroller, True, True, 0)

        self.placeholder = Gtk.Label(label="Connect to see sites.")
        self.placeholder.get_style_context().add_class("dim-label")
        self.placeholder.set_no_show_all(True)
        root.pack_start(self.placeholder, False, False, 0)

        self.update(controller.get_state())

    def _on_delete(self, *_):
        self.hide()
        return True

    def _on_action(self, _button):
        if self._conn in (ConnState.CONNECTED, ConnState.CONNECTING):
            self.controller.disconnect()
        else:
            self.controller.connect()

    def present_window(self):
        self.show_all()
        self.present()

    def update(self, state: AppState):
        self._conn = state.conn
        color, text = _DOT[state.conn]
        self.status_label.set_markup(
            f"<span size='x-large' weight='bold'><span color='{color}'>●</span> {text}</span>")

        busy = state.conn in (ConnState.CONNECTING, ConnState.DISCONNECTING)
        self.action_button.set_label(
            "Disconnect" if state.conn in (ConnState.CONNECTED, ConnState.CONNECTING) else "Connect")
        self.action_button.set_sensitive(state.active_account is not None and state.conn != ConnState.DISCONNECTING)

        acc = state.active_account
        self._values["Account"].set_text(f"{acc.display_name} ({acc.host})" if acc else "Not logged in")
        self._values["Organization"].set_text(org_display_name(state))
        self._values["Version"].set_text((state.status.version if state.status else "") or state.cli_version or "–")
        exit_node = state.status.exit_node if state.status else None
        self._values["Exit node"].set_text(
            f"{exit_node.endpoint or 'Exit node'} ({'connected' if exit_node.connected else 'down'})"
            if exit_node else "None")

        errors = [e for e in (state.last_error, state.status.error_message if state.status else "") if e]
        if errors:
            self.info_label.set_text(" · ".join(errors))
            self.info_label.show()
            self.info_bar.show()
        else:
            self.info_bar.hide()

        self._fill_peers(state)
        peers = state.status.peers if state.status else []
        self.placeholder.set_visible(not peers)
        if not peers:
            self.placeholder.set_text("Connecting…" if busy else
                                      "No sites" if state.conn == ConnState.CONNECTED else "Connect to see sites.")

    def _fill_peers(self, state: AppState):
        model, it = self.tree.get_selection().get_selected()
        selected_id = model[it][self.COL_ID] if it else None

        self.store.clear()
        for p in (state.status.peers if state.status else []):
            conn = "Local" if p.is_local else "Relay" if p.is_relay else "Direct"
            rtt = f"{p.rtt_ms:.1f} ms" if p.connected and p.rtt_ms > 0 else "–"
            self.store.append([p.site_id, p.name or f"Site {p.site_id}",
                               "● Connected" if p.connected else "○ Down", conn,
                               p.endpoint or "–", p.peer_address or "–", rtt,
                               format_relative(p.last_seen), p.rtt_ms])

        if selected_id is not None:
            for row in self.store:
                if row[self.COL_ID] == selected_id:
                    self.tree.get_selection().select_iter(row.iter)
                    break
