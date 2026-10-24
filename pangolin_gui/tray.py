"""Tray icon and menu for the Pangolin Linux client.

The menu is described toolkit-independently (menu_model.MenuNode) by
build_menu_model() and rendered by a backend:
  - sni.SniTray: own StatusNotifierItem over D-Bus. Left click opens the status
    window, right click shows the menu, middle click connects/disconnects.
  - tray_gtk.GtkTrayBackend: AppIndicator (one menu for all clicks) or Gtk.StatusIcon.
Mirrors the official Windows client's tray menu (ref/windows-ui/menu.go).
"""
from __future__ import annotations

import logging
import os
import pathlib
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Tuple

from pangolin_gui.i18n import _, current_language
from pangolin_gui.menu_model import LABEL, RADIO, MenuNode, separator, walk
from pangolin_gui.models import AppState, ConnState, OrgClient, Peer

log = logging.getLogger(__name__)

DOCS_URL = "https://docs.pangolin.net"
INSTALL_URL = "https://docs.pangolin.net/manage/clients/install-client"


# ---------------------------------------------------------------------------
# Pure Helper Functions (Work without GTK)
# ---------------------------------------------------------------------------

def get_status_label(state: AppState) -> str:
    """Return status line text from AppState."""
    if state.conn == ConnState.ERROR:
        if state.last_error:
            return state.last_error
        if state.status and state.status.error_message:
            return state.status.error_message
        return _("Error")
    if state.conn == ConnState.CONNECTED:
        return _("Connected")
    if state.conn == ConnState.CONNECTING:
        return _("Registering…")
    if state.conn == ConnState.DISCONNECTING:
        return _("Disconnecting…")
    return _("Disconnected")


def get_status_color(state: AppState) -> str:
    """Return status color name ('green', 'orange', 'gray', 'red') from AppState."""
    if state.conn == ConnState.ERROR:
        return "red"
    if state.conn == ConnState.CONNECTED:
        return "green"
    if state.conn == ConnState.CONNECTING:
        return "orange"
    if state.conn == ConnState.DISCONNECTING:
        return "gray"
    return "gray"


def format_status(state: AppState) -> Tuple[str, str]:
    """Return (label, color) tuple for AppState."""
    return get_status_label(state), get_status_color(state)


# Aliases
get_status_colour = get_status_color
status_label = get_status_label
status_color = get_status_color
status_colour = get_status_color


def format_relative_time(iso_str: Optional[str], now: Optional[datetime] = None) -> str:
    """Render relative time like '12s ago', '5m ago', '3h ago', '2d ago' from an ISO string."""
    if not iso_str:
        return ""
    try:
        clean_str = iso_str.strip()
        if clean_str.endswith("Z"):
            clean_str = clean_str[:-1] + "+00:00"
        t = datetime.fromisoformat(clean_str)
    except (ValueError, TypeError):
        return iso_str

    if now is None:
        if t.tzinfo is not None:
            now = datetime.now(timezone.utc)
        else:
            now = datetime.now()
    else:
        if t.tzinfo is not None and now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        elif t.tzinfo is None and now.tzinfo is not None:
            t = t.replace(tzinfo=now.tzinfo)

    diff = now - t
    seconds = int(diff.total_seconds())
    if seconds < 0:
        seconds = 0

    if seconds < 60:
        return _("{seconds}s ago").format(seconds=seconds)
    elif seconds < 3600:
        return _("{minutes}m ago").format(minutes=seconds // 60)
    elif seconds < 86400:
        return _("{hours}h ago").format(hours=seconds // 3600)
    return _("{days}d ago").format(days=seconds // 86400)


# Alias
relative_time = format_relative_time


def peer_connection_type(peer: Peer) -> str:
    """Return peer connection type: 'Local', 'Relay', or 'Direct'."""
    if getattr(peer, "is_local", False):
        return _("Local")
    if getattr(peer, "is_relay", False):
        return _("Relay")
    return _("Direct")


# Alias
get_peer_connection_type = peer_connection_type


def compute_menu_signature(state: AppState) -> tuple:
    """Compute an immutable signature of state for menu rebuilding comparison."""
    active_uid = state.active_account.user_id if state.active_account else None
    active_org_id = (
        state.status.org_id
        if state.status and state.status.org_id
        else (state.active_account.org_id if state.active_account else "")
    )
    st_label = get_status_label(state)
    accounts_sig = tuple(
        (acc.user_id, acc.display_name, acc.email, acc.host, acc.user_id == active_uid)
        for acc in state.accounts
    )
    orgs_sig = tuple(
        (org.org_id, org.name, org.org_id == active_org_id)
        for org in state.orgs
    )
    if state.conn == ConnState.CONNECTED and state.status and state.status.peers:
        peers_sig = tuple(
            (
                p.site_id,
                p.name,
                p.connected,
                peer_connection_type(p),
                p.endpoint,
                # last_seen/rtt change on every poll; bucket RTT coarsely and skip
                # last_seen so an open menu is not rebuilt every 2 s.
                int(p.rtt_ms // 25),
            )
            for p in state.status.peers
        )
    else:
        peers_sig = ()

    return (
        state.conn,
        st_label,
        state.cli_installed,
        state.cli_version,
        state.last_error,
        active_uid,
        active_org_id,
        accounts_sig,
        orgs_sig,
        peers_sig,
        clients_signature(state),
    )


def clients_signature(state: AppState) -> tuple:
    if state.conn != ConnState.CONNECTED:
        return ()
    return (state.clients_error,
            tuple((c.client_id, c.name, c.address, c.owner) for c in state.clients),
            tuple((s.site_id, s.name, s.online) for s in state.sites))


def client_menu_label(client: OrgClient) -> str:
    """Menu text for an online client, e.g. "laptop-anna  ·  100.90.128.7"."""
    return f"{client.name}  ·  {client.address}"


# Alias
menu_signature = compute_menu_signature


# ---------------------------------------------------------------------------
# Menu model (toolkit independent)
# ---------------------------------------------------------------------------

def build_menu_model(state: AppState, controller: Any) -> list[MenuNode]:
    """The whole tray menu for a state. Mirrors the Windows client (ref/windows-ui/menu.go)."""
    c = controller
    nodes: list[MenuNode] = []

    if not state.accounts:
        nodes.append(MenuNode("login", _("Log In…"), action=c.add_account))
        nodes.append(MenuNode("open_status", _("Open Status…"), action=c.open_status))
        nodes.append(separator("sep_top"))
        nodes.extend(_common_nodes(state, c))
        return nodes

    nodes.append(MenuNode("status", get_status_label(state), kind=LABEL))
    busy = state.conn in (ConnState.CONNECTING, ConnState.DISCONNECTING)
    if state.conn in (ConnState.CONNECTED, ConnState.CONNECTING, ConnState.DISCONNECTING):
        # A plain item, not a checkbox: its text always says what a click will do.
        nodes.append(MenuNode("toggle", _("Disconnect"), enabled=state.conn != ConnState.DISCONNECTING,
                              action=c.disconnect))
    else:
        nodes.append(MenuNode("toggle", _("Connect"), enabled=not busy, action=c.connect))
    nodes.append(MenuNode("open_status", _("Open Status…"), action=c.open_status))

    if state.conn == ConnState.CONNECTED:
        nodes.append(_sites_node(state, c))
        nodes.append(_clients_node(state, c))

    nodes.append(separator("sep_account"))
    nodes.append(_account_node(state, c))
    nodes.append(_org_node(state, c))
    nodes.append(separator("sep_common"))
    nodes.extend(_common_nodes(state, c))
    return nodes


def _sites_node(state: AppState, c: Any) -> MenuNode:
    peers = state.status.peers if state.status else []
    children: list[MenuNode] = []
    for p in peers:
        rtt = f"{p.rtt_ms:.1f} ms" if p.connected and p.rtt_ms > 0 else "—"
        details = [
            _("Status: {status}").format(status=_("Connected") if p.connected else _("Disconnected")),
            _("Connection: {type}").format(type=peer_connection_type(p)),
            _("Endpoint: {endpoint}").format(endpoint=p.endpoint or "—"),
            _("Last Seen: {last_seen}").format(last_seen=format_relative_time(p.last_seen) or "—"),
            _("RTT: {rtt}").format(rtt=rtt),
        ]
        children.append(MenuNode(
            f"site:{p.site_id}", p.name or _("Site {site_id}").format(site_id=p.site_id),
            icon_name="emblem-ok-symbolic" if p.connected else "",
            children=[MenuNode(f"site:{p.site_id}:{i}", text, kind=LABEL) for i, text in enumerate(details)]))

    # Sites of the org the tunnel does not use: clients only connect to sites with a
    # private resource they may use. A click explains that in a dialog.
    peer_ids = {p.site_id for p in peers}
    others = [s for s in state.sites if s.site_id not in peer_ids]
    if others and children:
        children.append(separator("sites:sep_other"))
    for s in others:
        label = (_("{name} – not via client") if s.online else _("{name} – offline")).format(name=s.name)
        children.append(MenuNode(f"site:other:{s.site_id}", label, icon_name="dialog-information-symbolic",
                                 action=lambda name=s.name, online=s.online: c.explain_site(name, online)))

    if not children:
        children.append(MenuNode("sites:none", _("No sites"), kind=LABEL))
    return MenuNode("sites", _("Sites"), children=children)


def _clients_node(state: AppState, c: Any) -> MenuNode:
    count = len(state.clients)
    title = _("Online Clients ({count})").format(count=count) if count else _("Online Clients")
    children: list[MenuNode] = []
    if state.clients:
        children.append(MenuNode("clients:hint", _("Click to copy the IP address"), kind=LABEL))
        children.append(separator("clients:sep"))
        for client in state.clients:
            children.append(MenuNode(
                f"client:{client.client_id}", client_menu_label(client), tooltip=client.owner,
                action=lambda ip=client.address, name=client.name: c.copy_client_ip(ip, name)))
    else:
        if state.clients_error == "forbidden":
            text = _("Your role may not list clients")
        elif state.clients_error:
            text = _("Could not load clients")
        else:
            text = _("No other clients online")
        children.append(MenuNode("clients:empty", text, kind=LABEL))
    children.append(separator("clients:sep2"))
    children.append(MenuNode("clients:refresh", _("Refresh"), action=c.refresh_clients))
    return MenuNode("clients", title, children=children)


def _account_node(state: AppState, c: Any) -> MenuNode:
    active_uid = state.active_account.user_id if state.active_account else None
    emails = [a.email for a in state.accounts]
    children: list[MenuNode] = []
    for acc in state.accounts:
        label = acc.display_name
        if emails.count(acc.email) > 1 and acc.host:
            label = f"{acc.display_name} ({acc.host})"
        children.append(MenuNode(f"account:{acc.user_id}", label, kind=RADIO,
                                 checked=acc.user_id == active_uid,
                                 action=lambda uid=acc.user_id: c.select_account(uid)))
    children.append(separator("account:sep"))
    children.append(MenuNode("account:add", _("Add Account…"), action=c.add_account))
    children.append(MenuNode("account:logout", _("Log Out"), enabled=active_uid is not None, action=c.logout))
    return MenuNode("account", _("Account"), children=children)


def _org_node(state: AppState, c: Any) -> MenuNode:
    active_org = (state.status.org_id if state.status and state.status.org_id
                  else (state.active_account.org_id if state.active_account else ""))
    children = [MenuNode(f"org:{o.org_id}", o.name, kind=RADIO, checked=o.org_id == active_org,
                         action=lambda oid=o.org_id: c.select_org(oid))
                for o in state.orgs]
    if not children:
        children.append(MenuNode("org:none", _("No Organizations"), kind=LABEL))
    return MenuNode("org", _("Organization"), children=children)


def _common_nodes(state: AppState, c: Any) -> list[MenuNode]:
    ver = state.cli_version or (state.status.version if state.status else "")
    more = [
        MenuNode("more:docs", _("Documentation"), action=lambda: c.open_url(DOCS_URL)),
        separator("more:sep"),
        MenuNode("more:version", _("Version {version}").format(version=ver) if ver else _("Version unknown"),
                 kind=LABEL),
    ]
    if not state.cli_installed:
        more.append(MenuNode("more:install", _("Install Pangolin CLI…"), action=lambda: c.open_url(INSTALL_URL)))
    return [
        MenuNode("preferences", _("Preferences…"), action=c.open_preferences),
        MenuNode("logs", _("Logs…"), action=c.open_logs),
        MenuNode("more", _("More"), children=more),
        separator("sep_quit"),
        MenuNode("quit", _("Quit Pangolin"), action=c.quit),
    ]


# ---------------------------------------------------------------------------
# TrayIcon: picks a backend and feeds it the menu model
# ---------------------------------------------------------------------------

def choose_backend(env: dict[str, str] | None = None) -> str:
    """"sni" (own StatusNotifierItem: left click = status window) or "gtk" (AppIndicator).

    PANGOLIN_TRAY=sni|gtk forces a backend; otherwise SNI is used when a
    StatusNotifierWatcher (KDE, GNOME AppIndicator extension, XFCE, waybar, …) is running.
    """
    forced = (env if env is not None else os.environ).get("PANGOLIN_TRAY", "").lower()
    if forced in ("sni", "gtk"):
        return forced
    try:
        from pangolin_gui import sni
        return "sni" if sni.sni_available() else "gtk"
    except Exception:  # Gio missing or broken bus
        log.debug("SNI check failed", exc_info=True)
        return "gtk"


class TrayIcon:
    """Tray icon + menu. Left click opens the status window where the backend allows it."""

    def __init__(self, controller: Any, icon_dir: pathlib.Path) -> None:
        self.controller = controller
        self.icon_dir = pathlib.Path(icon_dir)
        self._signature: Optional[tuple] = None
        self._last_state = AppState()
        self._resync_pending = False
        self.backend_name = choose_backend()
        if self.backend_name == "sni":
            from pangolin_gui.sni import SniTray
            self.backend = SniTray(self.icon_dir, on_activate=controller.open_status,
                                   on_secondary_activate=self._toggle_connection)
        else:
            from pangolin_gui.tray_gtk import GtkTrayBackend
            self.backend = GtkTrayBackend(self.icon_dir, on_activate=controller.open_status)
        log.info("tray backend: %s", self.backend_name)
        self.update(self._last_state)

    def update(self, state: AppState) -> None:
        self._last_state = state
        sig = (current_language(), compute_menu_signature(state))
        if sig != self._signature:
            self._signature = sig
            self.backend.set_menu(self._wrap_actions(build_menu_model(state, self.controller)))
        self.backend.set_icon(state.conn == ConnState.CONNECTED)
        self.backend.set_tooltip("Pangolin", get_status_label(state))

    def rebuild(self) -> None:
        """Force a rebuild, e.g. after a language change or a click."""
        self._signature = None
        self.update(self._last_state)

    def close(self) -> None:
        self.backend.close()

    def _toggle_connection(self) -> None:
        if self._last_state.conn in (ConnState.CONNECTED, ConnState.CONNECTING):
            self.controller.disconnect()
        else:
            self.controller.connect()

    def _wrap_actions(self, nodes: list[MenuNode]) -> list[MenuNode]:
        """After every click, rebuild from the real state.

        GTK toggles check/radio items itself on click; if the action is
        cancelled or fails, the menu would otherwise keep showing a wrong mark.
        """
        for node in walk(nodes):
            if node.action is not None:
                node.action = self._after_click(node.action)
        return nodes

    def _after_click(self, action: Callable[[], None]) -> Callable[[], None]:
        def run() -> None:
            try:
                action()
            finally:
                self._schedule_resync()
        return run

    def _schedule_resync(self) -> None:
        if self._resync_pending:
            return
        self._resync_pending = True
        from gi.repository import GLib

        def resync() -> bool:
            self._resync_pending = False
            self.rebuild()
            return False
        GLib.timeout_add(300, resync)
