"""Background polling that turns daemon status, account files and API data into AppState."""
from __future__ import annotations

import copy
import socket
from dataclasses import replace
import logging
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from pangolin_gui import accounts, cli, netinfo
from pangolin_gui.api import ApiError, PangolinApi
from pangolin_gui.i18n import _
from pangolin_gui.models import AppState, ConnState, OlmStatus, OrgClient
from pangolin_gui.olm_socket import OlmClient, OlmError

log = logging.getLogger(__name__)

TRANSITION_TIMEOUT = 120.0  # seconds before a stuck Connecting…/Disconnecting… is dropped
CLIENTS_INTERVAL = 30.0     # seconds between REST calls for the online-clients list


def derive_conn(status: Optional[OlmStatus], transition: Optional[ConnState]) -> ConnState:
    """Combine the daemon status with a user-initiated transition into one state."""
    if transition == ConnState.DISCONNECTING:
        return ConnState.DISCONNECTED if status is None else ConnState.DISCONNECTING
    if status is None:
        return ConnState.CONNECTING if transition == ConnState.CONNECTING else ConnState.DISCONNECTED
    if status.connected and status.registered:
        return ConnState.CONNECTED
    if status.error_message and not status.connected and transition != ConnState.CONNECTING:
        return ConnState.ERROR
    return ConnState.CONNECTING


def with_self(clients: list[OrgClient], own_ip: str, hostname: str) -> list[OrgClient]:
    """Mark this computer in the client list (first entry) so its IP can be copied too.

    Without permission to list clients the API returns nothing; this device is still
    added from its local tunnel IP.
    """
    if not own_ip:
        return list(clients)
    mine = next((c for c in clients if c.address == own_ip), None)
    me = replace(mine, is_self=True) if mine else OrgClient(
        client_id=0, name=hostname or "localhost", address=own_ip, online=True, is_self=True)
    return [me] + [c for c in clients if c.address != own_ip]


class StateManager:
    def __init__(self, on_change: Callable[[AppState], None], olm: OlmClient | None = None,
                 interval: float = 2.0, accounts_path: Path | None = None):
        self._on_change = on_change
        self._olm = olm or OlmClient()
        self._interval = interval
        self._accounts_path = accounts_path
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._state = AppState()
        self._last_emitted: Optional[AppState] = None
        self._transition: Optional[ConnState] = None
        self._transition_since = 0.0
        self._accounts_mtime: Optional[float] = -1.0
        self._orgs_for: Optional[tuple[str, str]] = None
        self._orgs_dirty = True
        self._clients_at = float("-inf")  # "never", independent of system uptime
        self._clients_key: Optional[tuple[str, str, str]] = None
        self._api_clients: list[OrgClient] = []
        self._api_sites: list = []
        self._clients_error = ""
        self._thread: Optional[threading.Thread] = None

    # -- public API (thread-safe) -------------------------------------------------
    def start(self) -> None:
        self._refresh_cli()
        self._thread = threading.Thread(target=self._loop, name="pangolin-state", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def get_state(self) -> AppState:
        with self._lock:
            return copy.deepcopy(self._state)

    def refresh_now(self, reload_orgs: bool = False, reload_cli: bool = False,
                    reload_clients: bool = False) -> None:
        if reload_orgs:
            self._orgs_dirty = True
        if reload_clients:
            self._clients_at = float("-inf")
        if reload_cli:
            self._refresh_cli()
        self._wake.set()

    def set_transition(self, conn: Optional[ConnState]) -> None:
        with self._lock:
            self._transition = conn
            self._transition_since = time.monotonic()
            if conn is not None:
                self._state.last_error = ""
        self.refresh_now()

    def set_error(self, message: str) -> None:
        with self._lock:
            self._state.last_error = message
            self._transition = None
        self.refresh_now()

    # -- worker -------------------------------------------------------------------
    def _refresh_cli(self) -> None:
        installed = cli.find_cli() is not None
        version = ""
        if installed:
            try:
                version = cli.version()
            except cli.CliError as exc:
                log.warning("pangolin version failed: %s", exc)
        with self._lock:
            self._state.cli_installed = installed
            self._state.cli_version = version

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._poll_once()
            except Exception:  # never let the poller die
                log.exception("state poll failed")
            self._wake.wait(self._interval)
            self._wake.clear()

    def _poll_once(self) -> None:
        status: Optional[OlmStatus] = None
        try:
            status = self._olm.get_status() if self._olm.is_running() else None
        except OlmError as exc:
            log.debug("olm status unavailable: %s", exc)
        if (status is None) != (self._state.status is None):
            log.info("tunnel daemon %s", "not running" if status is None else "running")

        self._reload_accounts()
        self._reload_orgs()
        self._reload_clients(status)

        with self._lock:
            transition = self._transition
            if transition and time.monotonic() - self._transition_since > TRANSITION_TIMEOUT:
                transition = self._transition = None
            conn = derive_conn(status, transition)
            # A transition ends once the daemon reached the target state.
            if (transition == ConnState.CONNECTING and conn == ConnState.CONNECTED) or \
               (transition == ConnState.DISCONNECTING and conn == ConnState.DISCONNECTED):
                self._transition = None
            self._state.status = status
            self._state.conn = conn
            snapshot = None
            if self._state != self._last_emitted:
                snapshot = copy.deepcopy(self._state)
                self._last_emitted = copy.deepcopy(self._state)
        if snapshot is not None:
            self._on_change(snapshot)

    def _reload_accounts(self) -> None:
        path = self._accounts_path or accounts.config_dir() / "accounts.json"
        try:
            mtime: Optional[float] = path.stat().st_mtime
        except OSError:
            mtime = None
        if mtime == self._accounts_mtime:
            return
        self._accounts_mtime = mtime
        accs, active = accounts.load_accounts(path)
        log.info("accounts loaded from %s: %d, active=%s", path, len(accs),
                 active.display_name if active else "none")
        with self._lock:
            self._state.accounts = accs
            self._state.active_account = active
            key = (active.user_id, active.host) if active else None
            if key != self._orgs_for:
                self._orgs_dirty = True
                self._state.orgs = []

    def _reload_orgs(self) -> None:
        if not self._orgs_dirty:
            return
        with self._lock:
            active = copy.deepcopy(self._state.active_account)
        self._orgs_dirty = False
        if active is None or not active.session_token:
            self._orgs_for = None
            return
        try:
            orgs = PangolinApi(active).list_orgs()
        except ApiError as exc:
            log.warning("could not load organizations: %s", exc)
            if exc.auth_expired:
                with self._lock:
                    self._state.last_error = _("Session expired. Please log in again.")
            return
        log.info("organizations loaded: %d", len(orgs))
        with self._lock:
            self._state.orgs = orgs
        self._orgs_for = (active.user_id, active.host)

    def _reload_clients(self, status: Optional[OlmStatus]) -> None:
        """Own tunnel IP every poll; clients and sites of the org at most every 30 s."""
        with self._lock:
            active = copy.deepcopy(self._state.active_account)
        connected = bool(status and status.connected and status.registered)
        own_ip = netinfo.interface_ipv4() if connected else ""
        org_id = (status.org_id if status else "") or (active.org_id if active else "")
        if not connected or active is None or not org_id or not active.session_token:
            self._clients_key = None
            self._api_clients, self._api_sites, self._clients_error = [], [], ""
        else:
            key = (active.user_id, active.host, org_id)
            if key != self._clients_key or time.monotonic() - self._clients_at >= CLIENTS_INTERVAL:
                self._clients_key, self._clients_at = key, time.monotonic()
                self._fetch_clients_and_sites(active, org_id)
        clients = with_self(self._api_clients, own_ip, socket.gethostname()) if connected else []
        with self._lock:
            self._state.own_ip = own_ip
            self._state.clients, self._state.clients_error = clients, self._clients_error
            self._state.sites = list(self._api_sites)

    def _fetch_clients_and_sites(self, active, org_id: str) -> None:
        try:
            self._api_clients = PangolinApi(active).list_online_clients(org_id)
            self._clients_error = ""
        except ApiError as exc:
            self._api_clients = []
            self._clients_error = "forbidden" if exc.forbidden else str(exc)
            log.info("could not list clients: %s", exc)
        log.debug("online clients: %d", len(self._api_clients))
        try:
            # Lets the tray name sites the tunnel does not connect to (no private resource).
            self._api_sites = PangolinApi(active).list_sites(org_id)
        except ApiError as exc:
            self._api_sites = []
            log.info("could not list sites: %s", exc)
