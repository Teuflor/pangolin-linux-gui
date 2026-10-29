"""Status window: connection summary and per-site peer table."""
from __future__ import annotations

import re
from datetime import datetime, timezone

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from pangolin_gui.i18n import _, N_  # noqa: E402
from pangolin_gui.models import AppState, ConnState  # noqa: E402

_DOT = {
    ConnState.CONNECTED: ("#22c55e", N_("Connected")),
    ConnState.CONNECTING: ("#f97316", N_("Connecting…")),
    ConnState.DISCONNECTING: ("#9ca3af", N_("Disconnecting…")),
    ConnState.DISCONNECTED: ("#9ca3af", N_("Disconnected")),
    ConnState.ERROR: ("#ef4444", N_("Error")),
}

_COLUMN_TITLES = (
    N_("Site"),
    N_("Status"),
    N_("Connection"),
    N_("Endpoint"),
    N_("Peer IP"),
    N_("RTT"),
    N_("Last seen"),
)


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
        return _("just now")
    if seconds < 60:
        return _("{seconds} s ago").format(seconds=seconds)
    if seconds < 3600:
        return _("{minutes} min ago").format(minutes=seconds // 60)
    if seconds < 86400:
        return _("{hours} h ago").format(hours=seconds // 3600)
    return _("{days} d ago").format(days=seconds // 86400)


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
        super().__init__(title=_("Pangolin Status"))
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
        for row, (label_text, key) in enumerate((
            (_("Account"), "Account"),
            (_("Organization"), "Organization"),
            (_("Version"), "Version"),
            (_("Exit node"), "Exit node"),
            (_("Own IP"), "Own IP"),
        )):
            name = Gtk.Label(label=label_text, xalign=0)
            name.get_style_context().add_class("dim-label")
            value = Gtk.Label(xalign=0, selectable=True)
            grid.attach(name, 0, row, 1, 1)
            grid.attach(value, 1, row, 1, 1)
            self._values[key] = value
        # Own tunnel IP with a copy button (same row as the "Own IP" label)
        self.copy_ip_button = Gtk.Button(label=_("Copy"), halign=Gtk.Align.START)
        self.copy_ip_button.get_style_context().add_class("flat")
        self.copy_ip_button.connect("clicked", self._on_copy_ip)
        grid.attach(self.copy_ip_button, 2, row, 1, 1)
        self._own_ip = ""

        self.action_button = Gtk.Button(label=_("Connect"), valign=Gtk.Align.START)
        self.action_button.connect("clicked", self._on_action)
        header.pack_end(self.action_button, False, False, 0)

        self.info_bar = Gtk.InfoBar(message_type=Gtk.MessageType.ERROR)
        self.info_label = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.info_bar.get_content_area().add(self.info_label)
        self.info_bar.set_no_show_all(True)
        root.pack_start(self.info_bar, False, False, 0)

        self.store = Gtk.ListStore(int, str, str, str, str, str, str, str, float)
        self.tree = Gtk.TreeView(model=self.store)
        columns = [(_COLUMN_TITLES[0], self.COL_NAME, self.COL_NAME),
                   (_COLUMN_TITLES[1], self.COL_STATUS, self.COL_STATUS),
                   (_COLUMN_TITLES[2], self.COL_CONN, self.COL_CONN),
                   (_COLUMN_TITLES[3], self.COL_ENDPOINT, self.COL_ENDPOINT),
                   (_COLUMN_TITLES[4], self.COL_IP, self.COL_IP),
                   (_COLUMN_TITLES[5], self.COL_RTT_TEXT, self.COL_RTT),
                   (_COLUMN_TITLES[6], self.COL_SEEN, self.COL_SEEN)]
        for title, text_col, sort_col in columns:
            col = Gtk.TreeViewColumn(_(title), Gtk.CellRendererText(), text=text_col)
            col.set_sort_column_id(sort_col)
            col.set_resizable(True)
            self.tree.append_column(col)
        self.store.set_sort_column_id(self.COL_NAME, Gtk.SortType.ASCENDING)

        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_shadow_type(Gtk.ShadowType.IN)
        scroller.add(self.tree)
        root.pack_start(scroller, True, True, 0)

        self.placeholder = Gtk.Label(label=_("Connect to see sites."))
        self.placeholder.get_style_context().add_class("dim-label")
        self.placeholder.set_no_show_all(True)
        root.pack_start(self.placeholder, False, False, 0)

        self.update(controller.get_state())

    def _on_delete(self, *_):
        self.hide()
        return True

    def _on_copy_ip(self, _button):
        if self._own_ip:
            self.controller.copy_client_ip(self._own_ip, _("this device"))

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
            f"<span size='x-large' weight='bold'><span color='{color}'>●</span> {GLib.markup_escape_text(_(text))}</span>")

        busy = state.conn in (ConnState.CONNECTING, ConnState.DISCONNECTING)
        self.action_button.set_label(
            _("Disconnect") if state.conn in (ConnState.CONNECTED, ConnState.CONNECTING) else _("Connect"))
        self.action_button.set_sensitive(state.active_account is not None and state.conn != ConnState.DISCONNECTING)

        acc = state.active_account
        self._values["Account"].set_text(f"{acc.display_name} ({acc.host})" if acc else _("Not logged in"))
        self._values["Organization"].set_text(org_display_name(state))
        self._values["Version"].set_text((state.status.version if state.status else "") or state.cli_version or "–")
        exit_node = state.status.exit_node if state.status else None
        if exit_node:
            node_name = exit_node.endpoint or _("Exit node")
            node_status = _("connected") if exit_node.connected else _("down")
            exit_node_text = f"{node_name} ({node_status})"
        else:
            exit_node_text = _("None")
        self._values["Exit node"].set_text(exit_node_text)
        self._own_ip = state.own_ip if state.conn == ConnState.CONNECTED else ""
        self._values["Own IP"].set_text(self._own_ip or "–")
        self.copy_ip_button.set_sensitive(bool(self._own_ip))

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
            self.placeholder.set_text(_("Connecting…") if busy else
                                      _("No sites") if state.conn == ConnState.CONNECTED else _("Connect to see sites."))

    def _fill_peers(self, state: AppState):
        model, it = self.tree.get_selection().get_selected()
        selected_id = model[it][self.COL_ID] if it else None

        self.store.clear()
        for p in (state.status.peers if state.status else []):
            conn = _("Local") if p.is_local else _("Relay") if p.is_relay else _("Direct")
            rtt = f"{p.rtt_ms:.1f} ms" if p.connected and p.rtt_ms > 0 else "–"
            site_name = p.name or _("Site {site_id}").format(site_id=p.site_id)
            status_text = _("● Connected") if p.connected else _("○ Down")
            self.store.append([p.site_id, site_name,
                               status_text, conn,
                               p.endpoint or "–", p.peer_address or "–", rtt,
                               format_relative(p.last_seen), p.rtt_ms])

        if selected_id is not None:
            for row in self.store:
                if row[self.COL_ID] == selected_id:
                    self.tree.get_selection().select_iter(row.iter)
                    break
