"""Linux system tray icon and menu for Pangolin GUI.

Mirrors the official Windows client's tray menu (ref/windows-ui/menu.go) as closely
as GTK3 menus allow, using AyatanaAppIndicator3 with fallbacks to AppIndicator3 and
Gtk.StatusIcon.
"""
from __future__ import annotations

import pathlib
from datetime import datetime, timezone
from typing import Any, Optional, Tuple

from pangolin_gui.i18n import _
from pangolin_gui.models import AppState, ConnState, OrgClient, Peer

# Guarded imports so pure helpers can be imported and tested without GTK installed
_GTK_AVAILABLE = False
_APP_INDICATOR_KIND: Optional[str] = None
Gtk: Any = None
GLib: Any = None
AppIndicator3: Any = None

try:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import GLib as _GLib, Gtk as _Gtk

    Gtk = _Gtk
    GLib = _GLib
    _GTK_AVAILABLE = True
except (ImportError, ValueError):
    pass

if _GTK_AVAILABLE:
    try:
        gi.require_version("AyatanaAppIndicator3", "0.1")
        from gi.repository import AyatanaAppIndicator3 as _Indicator

        AppIndicator3 = _Indicator
        _APP_INDICATOR_KIND = "AyatanaAppIndicator3"
    except (ImportError, ValueError):
        try:
            gi.require_version("AppIndicator3", "0.1")
            from gi.repository import AppIndicator3 as _Indicator

            AppIndicator3 = _Indicator
            _APP_INDICATOR_KIND = "AppIndicator3"
        except (ImportError, ValueError):
            AppIndicator3 = None
            _APP_INDICATOR_KIND = "StatusIcon"


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
            tuple((c.client_id, c.name, c.address, c.owner) for c in state.clients))


def client_menu_label(client: OrgClient) -> str:
    """Menu text for an online client, e.g. "laptop-anna  ·  100.90.128.7"."""
    return f"{client.name}  ·  {client.address}"


# Alias
menu_signature = compute_menu_signature


# ---------------------------------------------------------------------------
# TrayIcon Class (GTK3 / AppIndicator)
# ---------------------------------------------------------------------------

class TrayIcon:
    """System tray icon and popup menu for Pangolin Linux client."""

    def __init__(self, controller: Any, icon_dir: pathlib.Path) -> None:
        if not _GTK_AVAILABLE:
            raise RuntimeError("GTK 3 is not available in the current environment")

        self.controller = controller
        self.icon_dir = pathlib.Path(icon_dir)
        self._menu_signature: Optional[tuple] = None
        self._menu: Optional[Gtk.Menu] = None
        self._indicator: Any = None
        self._status_icon: Any = None
        self._connect_toggle_handler: Optional[int] = None

        initial_icon_name = "network-vpn"
        gray_file = self.icon_dir / "pangolin-gray.png"
        if gray_file.is_file():
            initial_icon_name = str(gray_file)

        if _APP_INDICATOR_KIND in ("AyatanaAppIndicator3", "AppIndicator3") and AppIndicator3 is not None:
            try:
                self._indicator = AppIndicator3.Indicator.new(
                    "pangolin-gui",
                    initial_icon_name,
                    AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
                )
                self._indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
                if self.icon_dir.is_dir():
                    try:
                        self._indicator.set_icon_theme_path(str(self.icon_dir))
                    except Exception:
                        pass
            except Exception:
                self._indicator = None

        if self._indicator is None:
            # Fall back to Gtk.StatusIcon
            self._status_icon = Gtk.StatusIcon()
            self._status_icon.connect("popup-menu", self._on_status_icon_popup)
            self._status_icon.connect("activate", self._on_status_icon_activate)
            self._apply_status_icon_image(connected=False)

        self._last_state: AppState = AppState()
        # AppIndicator needs a menu before the first state arrives
        self.update(self._last_state)

    def _on_status_icon_popup(self, status_icon: Any, button: int, activate_time: int) -> None:
        if self._menu:
            self._menu.popup(None, None, Gtk.StatusIcon.position_menu, status_icon, button, activate_time)

    def _on_status_icon_activate(self, status_icon: Any) -> None:
        if self._menu:
            self._menu.popup(None, None, Gtk.StatusIcon.position_menu, status_icon, 0, Gtk.get_current_event_time())

    def update(self, state: AppState) -> None:
        """Update tray menu and icon from AppState, rebuilding menu only when signature changes."""
        self._last_state = state
        sig = compute_menu_signature(state)
        if sig != self._menu_signature or self._menu is None:
            self._menu_signature = sig
            self._menu = self._build_menu(state)
            self._menu.show_all()
            if self._indicator is not None:
                self._indicator.set_menu(self._menu)

        is_connected = (state.conn == ConnState.CONNECTED)
        self._update_icon(is_connected)
        self._update_tooltip(state)

    def rebuild(self) -> None:
        """Reset the cached menu signature and rebuild the menu from the last state."""
        self._menu_signature = None
        self.update(self._last_state)

    def _update_icon(self, connected: bool) -> None:
        filename = "pangolin-orange.png" if connected else "pangolin-gray.png"
        icon_file = self.icon_dir / filename

        if self._indicator is not None:
            try:
                if icon_file.is_file():
                    try:
                        self._indicator.set_icon_full(str(icon_file), "Pangolin")
                    except Exception:
                        try:
                            self._indicator.set_icon(str(icon_file))
                        except Exception:
                            self._indicator.set_icon(icon_file.stem)
                else:
                    self._indicator.set_icon("network-vpn")
            except Exception:
                pass
        elif self._status_icon is not None:
            self._apply_status_icon_image(connected)

    def _apply_status_icon_image(self, connected: bool) -> None:
        if self._status_icon is None:
            return
        filename = "pangolin-orange.png" if connected else "pangolin-gray.png"
        icon_file = self.icon_dir / filename
        try:
            if icon_file.is_file():
                self._status_icon.set_from_file(str(icon_file))
            else:
                self._status_icon.set_from_icon_name("network-vpn")
        except Exception:
            try:
                self._status_icon.set_from_icon_name("network-vpn")
            except Exception:
                pass

    def _update_tooltip(self, state: AppState) -> None:
        status_text = get_status_label(state)
        tooltip = _("Pangolin: {status}").format(status=status_text)
        if self._status_icon is not None:
            try:
                self._status_icon.set_tooltip_text(tooltip)
            except Exception:
                pass
        elif self._indicator is not None:
            try:
                self._indicator.set_title(tooltip)
            except Exception:
                pass

    def _build_menu(self, state: AppState) -> Gtk.Menu:
        menu = Gtk.Menu()

        if not state.accounts:
            # No account -> "Log In…" item instead of account/org sections
            login_item = Gtk.MenuItem(label=_("Log In…"))

            def on_login(_: Any) -> None:
                if hasattr(self.controller, "add_account"):
                    self.controller.add_account()
                elif hasattr(self.controller, "login"):
                    self.controller.login()

            login_item.connect("activate", on_login)
            menu.append(login_item)

            menu.append(Gtk.SeparatorMenuItem())
            self._append_common_items(menu, state)
            return menu

        # 1. Status line
        status_text = get_status_label(state)
        status_item = Gtk.MenuItem(label=status_text)
        status_item.set_sensitive(False)
        menu.append(status_item)

        # 2. Connect/Disconnect toggle
        is_connected = (state.conn in (ConnState.CONNECTED, ConnState.CONNECTING))
        toggle_label = _("Disconnect") if is_connected else _("Connect")
        toggle_item = Gtk.CheckMenuItem(label=toggle_label)
        self._connect_toggle_handler = toggle_item.connect("toggled", self._on_connect_toggled)
        toggle_item.handler_block(self._connect_toggle_handler)
        toggle_item.set_active(is_connected)
        toggle_item.handler_unblock(self._connect_toggle_handler)
        if state.conn in (ConnState.CONNECTING, ConnState.DISCONNECTING):
            toggle_item.set_sensitive(False)
        menu.append(toggle_item)

        # 3. "Sites" submenu (when connected)
        if state.conn == ConnState.CONNECTED:
            sites_item = Gtk.MenuItem(label=_("Sites"))
            sites_menu = Gtk.Menu()

            open_status_item = Gtk.MenuItem(label=_("Open Status…"))
            open_status_item.connect("activate", lambda _: self.controller.open_status())
            sites_menu.append(open_status_item)
            sites_menu.append(Gtk.SeparatorMenuItem())

            peers = state.status.peers if state.status and state.status.peers else []
            if peers:
                for peer in peers:
                    peer_item = Gtk.MenuItem(label=peer.name)
                    peer_menu = Gtk.Menu()

                    # Status
                    st_val = _("Connected") if peer.connected else _("Disconnected")
                    st_label = _("Status: {status}").format(status=st_val)
                    st_item = Gtk.MenuItem(label=st_label)
                    st_item.set_sensitive(False)
                    peer_menu.append(st_item)

                    # Connection Direct/Relay/Local
                    conn_type = peer_connection_type(peer)
                    conn_item = Gtk.MenuItem(label=_("Connection: {type}").format(type=conn_type))
                    conn_item.set_sensitive(False)
                    peer_menu.append(conn_item)

                    # Endpoint
                    ep_val = peer.endpoint if peer.endpoint else "—"
                    ep_item = Gtk.MenuItem(label=_("Endpoint: {endpoint}").format(endpoint=ep_val))
                    ep_item.set_sensitive(False)
                    peer_menu.append(ep_item)

                    # Last Seen relative
                    ls_rel = format_relative_time(peer.last_seen)
                    ls_val = ls_rel if ls_rel else "—"
                    ls_item = Gtk.MenuItem(label=_("Last Seen: {last_seen}").format(last_seen=ls_val))
                    ls_item.set_sensitive(False)
                    peer_menu.append(ls_item)

                    # RTT
                    if peer.connected and peer.rtt_ms > 0:
                        rtt_val = f"{peer.rtt_ms:.1f} ms"
                    else:
                        rtt_val = "—"
                    rtt_item = Gtk.MenuItem(label=_("RTT: {rtt}").format(rtt=rtt_val))
                    rtt_item.set_sensitive(False)
                    peer_menu.append(rtt_item)

                    peer_item.set_submenu(peer_menu)
                    sites_menu.append(peer_item)
            else:
                no_sites = Gtk.MenuItem(label=_("No sites"))
                no_sites.set_sensitive(False)
                sites_menu.append(no_sites)

            sites_item.set_submenu(sites_menu)
            menu.append(sites_item)
            menu.append(self._build_clients_submenu(state))

        menu.append(Gtk.SeparatorMenuItem())

        # 4. "Account" submenu
        account_item = Gtk.MenuItem(label=_("Account"))
        account_menu = Gtk.Menu()

        email_counts: dict[str, int] = {}
        for acc in state.accounts:
            email_counts[acc.email] = email_counts.get(acc.email, 0) + 1

        active_uid = state.active_account.user_id if state.active_account else None
        radio_group = None
        for acc in state.accounts:
            label = acc.display_name
            if email_counts.get(acc.email, 0) > 1 and acc.host:
                label = f"{acc.display_name} ({acc.host})"
            radio = Gtk.RadioMenuItem.new_with_label(radio_group, label)
            radio_group = radio.get_group()
            is_active = (acc.user_id == active_uid)
            radio.set_active(is_active)

            def on_select_acc(item: Any, uid: str = acc.user_id) -> None:
                if item.get_active() and uid != active_uid:
                    self.controller.select_account(uid)

            radio.connect("toggled", on_select_acc)
            account_menu.append(radio)

        account_menu.append(Gtk.SeparatorMenuItem())

        add_acc_item = Gtk.MenuItem(label=_("Add Account…"))
        add_acc_item.connect("activate", lambda _: self.controller.add_account())
        account_menu.append(add_acc_item)

        logout_item = Gtk.MenuItem(label=_("Log Out"))
        logout_item.connect("activate", lambda _: self.controller.logout())
        if not active_uid:
            logout_item.set_sensitive(False)
        account_menu.append(logout_item)

        account_item.set_submenu(account_menu)
        menu.append(account_item)

        # 5. "Organization" submenu
        org_item = Gtk.MenuItem(label=_("Organization"))
        org_menu = Gtk.Menu()

        active_org_id = (
            state.status.org_id
            if state.status and state.status.org_id
            else (state.active_account.org_id if state.active_account else "")
        )

        if not state.orgs:
            empty_item = Gtk.MenuItem(label=_("No Organizations"))
            empty_item.set_sensitive(False)
            org_menu.append(empty_item)
        else:
            org_group = None
            for org in state.orgs:
                radio = Gtk.RadioMenuItem.new_with_label(org_group, org.name)
                org_group = radio.get_group()
                is_active = (org.org_id == active_org_id)
                radio.set_active(is_active)

                def on_select_org(item: Any, oid: str = org.org_id) -> None:
                    if item.get_active() and oid != active_org_id:
                        self.controller.select_org(oid)

                radio.connect("toggled", on_select_org)
                org_menu.append(radio)

        org_item.set_submenu(org_menu)
        menu.append(org_item)

        menu.append(Gtk.SeparatorMenuItem())
        self._append_common_items(menu, state)

        return menu

    def _build_clients_submenu(self, state: AppState) -> Gtk.MenuItem:
        """Online clients of the org; clicking one copies its tunnel IP."""
        count = len(state.clients)
        title = _("Online Clients ({count})").format(count=count) if count else _("Online Clients")
        clients_item = Gtk.MenuItem(label=title)
        sub = Gtk.Menu()

        if state.clients:
            hint = Gtk.MenuItem(label=_("Click to copy the IP address"))
            hint.set_sensitive(False)
            sub.append(hint)
            sub.append(Gtk.SeparatorMenuItem())
            for client in state.clients:
                item = Gtk.MenuItem(label=client_menu_label(client))
                if client.owner:
                    item.set_tooltip_text(client.owner)
                item.connect("activate", lambda _w, ip=client.address, name=client.name:
                             self.controller.copy_client_ip(ip, name))
                sub.append(item)
        else:
            if state.clients_error == "forbidden":
                text = _("Your role may not list clients")
            elif state.clients_error:
                text = _("Could not load clients")
            else:
                text = _("No other clients online")
            empty = Gtk.MenuItem(label=text)
            empty.set_sensitive(False)
            sub.append(empty)

        sub.append(Gtk.SeparatorMenuItem())
        refresh = Gtk.MenuItem(label=_("Refresh"))
        refresh.connect("activate", lambda _w: self.controller.refresh_clients())
        sub.append(refresh)

        clients_item.set_submenu(sub)
        return clients_item

    def _append_common_items(self, menu: Gtk.Menu, state: AppState) -> None:
        pref_item = Gtk.MenuItem(label=_("Preferences…"))
        pref_item.connect("activate", lambda _: self.controller.open_preferences())
        menu.append(pref_item)

        logs_item = Gtk.MenuItem(label=_("Logs…"))
        logs_item.connect("activate", lambda _: self.controller.open_logs())
        menu.append(logs_item)

        more_item = self._build_more_submenu(state)
        menu.append(more_item)

        menu.append(Gtk.SeparatorMenuItem())

        quit_item = Gtk.MenuItem(label=_("Quit Pangolin"))
        quit_item.connect("activate", lambda _: self.controller.quit())
        menu.append(quit_item)

    def _build_more_submenu(self, state: AppState) -> Gtk.MenuItem:
        more_item = Gtk.MenuItem(label=_("More"))
        more_menu = Gtk.Menu()

        docs_item = Gtk.MenuItem(label=_("Documentation"))
        docs_item.connect("activate", lambda _: self.controller.open_url("https://docs.pangolin.net"))
        more_menu.append(docs_item)

        more_menu.append(Gtk.SeparatorMenuItem())

        ver = state.cli_version
        if not ver and state.status and state.status.version:
            ver = state.status.version
        ver_label = _("Version {version}").format(version=ver) if ver else _("Version unknown")
        ver_item = Gtk.MenuItem(label=ver_label)
        ver_item.set_sensitive(False)
        more_menu.append(ver_item)

        if not state.cli_installed:
            cli_item = Gtk.MenuItem(label=_("Install Pangolin CLI…"))
            cli_item.connect(
                "activate",
                lambda _: self.controller.open_url("https://docs.pangolin.net/manage/clients/install-client"),
            )
            more_menu.append(cli_item)

        more_item.set_submenu(more_menu)
        return more_item

    def _on_connect_toggled(self, item: Gtk.CheckMenuItem) -> None:
        if item.get_active():
            self.controller.connect()
        else:
            self.controller.disconnect()
