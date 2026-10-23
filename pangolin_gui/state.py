"""Background polling that turns daemon status, account files and API data into AppState."""
from __future__ import annotations

import copy
import logging
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from pangolin_gui import accounts, cli
from pangolin_gui.api import ApiError, PangolinApi
from pangolin_gui.models import AppState, ConnState, OlmStatus
from pangolin_gui.olm_socket import OlmClient, OlmError

log = logging.getLogger(__name__)

TRANSITION_TIMEOUT = 120.0  # seconds before a stuck Connecting…/Disconnecting… is dropped


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

    def refresh_now(self, reload_orgs: bool = False, reload_cli: bool = False) -> None:
        if reload_orgs:
            self._orgs_dirty = True
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

        self._reload_accounts()
        self._reload_orgs()

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
                    self._state.last_error = "Session expired. Please log in again."
            return
        with self._lock:
            self._state.orgs = orgs
        self._orgs_for = (active.user_id, active.host)
