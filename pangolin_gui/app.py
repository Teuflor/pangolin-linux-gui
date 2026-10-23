"""Gtk.Application and controller: wires state polling, tray and windows to CLI actions."""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from pangolin_gui import cli, i18n, settings  # noqa: E402
from pangolin_gui.i18n import _  # noqa: E402
from pangolin_gui.models import AppState, ConnState  # noqa: E402
from pangolin_gui.olm_socket import OlmClient, OlmError  # noqa: E402
from pangolin_gui.state import StateManager  # noqa: E402

log = logging.getLogger(__name__)

APP_ID = "net.pangolin.LinuxClient"
ROOT = Path(__file__).resolve().parent.parent
ICON_DIR = ROOT / "data" / "icons"
ASKPASS = ROOT / "bin" / "pangolin-gui-askpass"


class PangolinApp(Gtk.Application):
    def __init__(self, start_hidden: bool = False):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self._start_hidden = start_hidden
        self._first_activate = True
        self.state_mgr = StateManager(lambda s: GLib.idle_add(self._on_state, s))
        self._state = AppState()
        self.tray = None
        self._windows: dict[str, Gtk.Window] = {}
        self._login_dialog = None
        self._connect_after_login = False  # login was started by Connect -> connect when done

    # -- Gtk.Application ----------------------------------------------------------
    def do_startup(self):
        Gtk.Application.do_startup(self)
        i18n.set_language(settings.GuiSettings.load().language)
        self.hold()  # keep running without windows (tray app)
        from pangolin_gui.tray import TrayIcon
        try:
            self.tray = TrayIcon(self, ICON_DIR)
        except Exception:
            log.exception("tray icon unavailable; falling back to the status window")
            self.tray = None
            self._start_hidden = False
        log.info("started: language=%s cli=%s tray=%s", i18n.current_language(),
                 cli.find_cli() or "missing", getattr(self.tray, "backend_name", "none"))
        self.state_mgr.start()
        if settings.GuiSettings.load().connect_on_start:
            GLib.timeout_add_seconds(3, self._auto_connect)

    def do_activate(self):
        # First launch from autostart stays in the tray; any later launch shows the window.
        if self._first_activate and self._start_hidden:
            self._first_activate = False
            return
        self._first_activate = False
        self.open_status()

    def do_shutdown(self):
        self.state_mgr.stop()
        Gtk.Application.do_shutdown(self)

    # -- state --------------------------------------------------------------------
    def _on_state(self, state: AppState):
        if state.conn != self._state.conn:
            log.info("connection: %s -> %s", self._state.conn.value, state.conn.value)
        self._state = state
        if self.tray is not None:
            self.tray.update(state)
        for window in self._windows.values():
            if window.get_visible():
                window.update(state)
        return False

    def get_state(self) -> AppState:
        return self._state

    def _auto_connect(self):
        state = self.get_state()
        if state.accounts and state.conn == ConnState.DISCONNECTED:
            log.info("auto-connect on start")
            self.connect()
        return False

    # -- helpers ------------------------------------------------------------------
    def _run(self, work: Callable[[], None], on_error: Callable[[str], None] | None = None,
             on_success: Callable[[], None] | None = None) -> None:
        """Run blocking work off the GTK thread; report errors back on it."""
        report = on_error or self._report_error

        def on_main(fn, *args):
            fn(*args)
            return False  # one-shot idle callback

        def target():
            try:
                work()
            except (cli.CliError, OlmError) as exc:
                msg = str(exc) or exc.__class__.__name__
                log.warning("action failed: %s", msg)
                GLib.idle_add(on_main, report, msg)
            except Exception as exc:  # unexpected – still surface it
                log.exception("action crashed")
                GLib.idle_add(on_main, report, str(exc))
            else:
                if on_success:
                    GLib.idle_add(on_main, on_success)
            finally:
                self.state_mgr.refresh_now()
        threading.Thread(target=target, daemon=True).start()

    def _report_error(self, message: str):
        self.state_mgr.set_error(message)
        self.notify("Pangolin", message)

    def notify(self, title: str, body: str):
        note = Gio.Notification.new(title)
        note.set_body(body)
        self.send_notification(None, note)

    def _require_cli(self) -> bool:
        if cli.find_cli():
            return True
        self._report_error(_("The Pangolin CLI is not installed. See More → Install Pangolin CLI…"))
        return False

    # -- controller API used by tray and windows ----------------------------------
    def connect(self):
        if not self._require_cli():
            return
        state = self.get_state()
        account = state.active_account
        if account is None and len(state.accounts) == 1:
            # Logged in once, but the CLI has no active account: use the only one.
            only = state.accounts[0]
            log.info("connect: no active account, selecting the only account %s", only.display_name)
            self.state_mgr.set_transition(ConnState.CONNECTING)

            def work():
                cli.select_account(only.email, only.host)
                cli.up(org_id=only.org_id or None, askpass=str(ASKPASS))
            self._run(work, on_error=self._connect_failed)
            return
        if account is None:
            log.info("connect: no account selected -> login")
            self._connect_after_login = True
            self.add_account()
            return
        log.info("connect: account=%s org=%s", account.display_name, account.org_id or "default")
        self.state_mgr.set_transition(ConnState.CONNECTING)
        self._run(lambda: cli.up(org_id=account.org_id or None, askpass=str(ASKPASS)),
                  on_error=self._connect_failed)

    def _connect_failed(self, message: str):
        lower = message.lower()
        if "incorrect password" in lower or "a password is required" in lower:
            message = _("Authentication failed or was cancelled.")
        elif any(k in lower for k in ("not logged in", "unauthorized", "session expired", "log in again")):
            # Session gone: log in again on the same server without asking for the URL.
            log.info("connect failed because the session is gone -> re-login")
            self.state_mgr.set_error("")
            self._connect_after_login = True
            self.add_account(host=self._known_host(), start=True)
            return
        self._report_error(message)

    def disconnect(self):
        log.info("disconnect")
        self.state_mgr.set_transition(ConnState.DISCONNECTING)

        def work():
            try:
                cli.down()
            except cli.CliError:
                # Fall back to the daemon API directly (e.g. CLI missing)
                OlmClient().exit()
        self._run(work)

    def select_org(self, org_id: str):
        state = self.get_state()
        if state.active_account and state.active_account.org_id == org_id:
            return
        if state.conn == ConnState.CONNECTED:
            self.state_mgr.set_transition(ConnState.CONNECTING)
        log.info("select org %s", org_id)
        self._run(lambda: cli.select_org(org_id),
                  on_success=lambda: self.state_mgr.refresh_now(reload_orgs=False))

    def select_account(self, user_id: str):
        state = self.get_state()
        account = next((a for a in state.accounts if a.user_id == user_id), None)
        if account is None or (state.active_account and state.active_account.user_id == user_id):
            return
        was_connected = state.conn in (ConnState.CONNECTED, ConnState.CONNECTING)
        log.info("select account %s", account.display_name)

        def work():
            if was_connected:
                cli.down()
            cli.select_account(account.email, account.host)
        self._run(work, on_success=lambda: self.state_mgr.refresh_now(reload_orgs=True))

    def _known_host(self) -> str | None:
        state = self.get_state()
        account = state.active_account or (state.accounts[0] if state.accounts else None)
        return account.host if account else None

    def add_account(self, host: str | None = None, start: bool = False):
        """Open the login dialog. The server URL is prefilled with the known server;
        with start=True the login begins right away without asking for it."""
        if not self._require_cli():
            return
        if self._login_dialog is not None:
            self._login_dialog.present()
            return
        from pangolin_gui.windows.login_dialog import LoginDialog
        host = host or self._known_host()
        log.info("login dialog: host=%s start=%s", host or "-", start)
        self._login_dialog = LoginDialog(None, controller=self, host=host, start=start)
        self._login_dialog.connect("destroy", self._on_login_dialog_closed)
        self._login_dialog.show_all()
        self._login_dialog.present()

    def _on_login_dialog_closed(self, *_args):
        self._login_dialog = None
        if self._connect_after_login:
            GLib.timeout_add(100, self._drop_pending_connect)

    def _drop_pending_connect(self):
        # on_login_finished runs first if the login completed; otherwise it was cancelled
        self._connect_after_login = False
        return False

    def on_login_finished(self, ok: bool):
        log.info("login finished: ok=%s", ok)
        self.state_mgr.refresh_now(reload_orgs=True)
        connect_now, self._connect_after_login = self._connect_after_login, False
        if not ok:
            return
        self.notify("Pangolin", _("Logged in successfully."))
        if connect_now:
            # Give the poller a moment to load the new accounts.json, then connect.
            GLib.timeout_add(1500, self._connect_once)

    def _connect_once(self):
        self.connect()
        return False

    def logout(self):
        dialog = Gtk.MessageDialog(message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.OK_CANCEL,
                                   text=_("Log out of Pangolin?"))
        dialog.format_secondary_text(_("Any active connection will be disconnected."))
        response = dialog.run()
        dialog.destroy()
        if response != Gtk.ResponseType.OK:
            return
        running = self.get_state().conn != ConnState.DISCONNECTED

        def work():
            if running:  # logout prompts interactively while a client runs
                cli.down()
            cli.logout()
        self._run(work, on_success=lambda: self.state_mgr.refresh_now(reload_orgs=True))

    def read_logs(self, callback: Callable[[str], None]):
        def work():
            try:
                text = cli.read_logs(1000)
            except cli.CliError as exc:
                text = f"ERROR: {exc}"
            callback(text)
        threading.Thread(target=work, daemon=True).start()

    def apply_cli_config(self, changes: dict[str, str], callback: Callable[[str | None], None]):
        def work():
            for key, value in changes.items():
                cli.config_set(key, value)
        self._run(work, on_error=lambda msg: callback(msg), on_success=lambda: callback(None))

    def _window(self, name: str):
        if name not in self._windows:
            if name == "status":
                from pangolin_gui.windows.status_window import StatusWindow as cls
            elif name == "logs":
                from pangolin_gui.windows.logs_window import LogsWindow as cls
            else:
                from pangolin_gui.windows.preferences import PreferencesWindow as cls
            window = cls(self)
            self.add_window(window)
            self._windows[name] = window
        window = self._windows[name]
        window.update(self.get_state())
        window.present_window()

    def copy_client_ip(self, ip: str, name: str = ""):
        from pangolin_gui import clipboard
        if clipboard.copy_text(ip):
            self.notify("Pangolin", _("Copied {ip} ({name}) to the clipboard.").format(ip=ip, name=name or ip))
        else:
            self._report_error(_("Could not access the clipboard. Install wl-clipboard or xclip."))

    def refresh_clients(self):
        self.state_mgr.refresh_now(reload_clients=True)

    def apply_language(self, code: str):
        """Switch the UI language at runtime: rebuild tray, recreate windows."""
        i18n.set_language(code)
        reopen = [name for name, w in self._windows.items() if w.get_visible() and name != "preferences"]
        for window in self._windows.values():
            window.destroy()
        self._windows.clear()
        if self.tray is not None:
            self.tray.rebuild()
        for name in reopen:
            self._window(name)

    def open_status(self):
        self._window("status")

    def open_logs(self):
        self._window("logs")

    def open_preferences(self):
        self._window("preferences")

    def open_url(self, url: str):
        try:
            Gio.AppInfo.launch_default_for_uri(url, None)
        except GLib.Error as exc:
            self._report_error(_("Could not open browser: {error}").format(error=exc.message))

    def quit(self):
        # The tunnel daemon keeps running independently, like `pangolin up` does.
        self.release()
        Gtk.Application.quit(self)
