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
        if state.active_account and state.conn == ConnState.DISCONNECTED:
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
        if state.active_account is None:
            self.add_account()
            return
        org = state.active_account.org_id or None
        self.state_mgr.set_transition(ConnState.CONNECTING)
        self._run(lambda: cli.up(org_id=org, askpass=str(ASKPASS)), on_error=self._connect_failed)

    def _connect_failed(self, message: str):
        if "incorrect password" in message.lower() or "a password is required" in message.lower():
            message = _("Authentication failed or was cancelled.")
        self._report_error(message)

    def disconnect(self):
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
        self._run(lambda: cli.select_org(org_id),
                  on_success=lambda: self.state_mgr.refresh_now(reload_orgs=False))

    def select_account(self, user_id: str):
        state = self.get_state()
        account = next((a for a in state.accounts if a.user_id == user_id), None)
        if account is None or (state.active_account and state.active_account.user_id == user_id):
            return
        was_connected = state.conn in (ConnState.CONNECTED, ConnState.CONNECTING)

        def work():
            if was_connected:
                cli.down()
            cli.select_account(account.email, account.host)
        self._run(work, on_success=lambda: self.state_mgr.refresh_now(reload_orgs=True))

    def add_account(self):
        if not self._require_cli():
            return
        if self._login_dialog is not None:
            self._login_dialog.present()
            return
        from pangolin_gui.windows.login_dialog import LoginDialog
        self._login_dialog = LoginDialog(None, controller=self)
        self._login_dialog.connect("destroy", lambda *_: setattr(self, "_login_dialog", None))
        self._login_dialog.show_all()
        self._login_dialog.present()

    def on_login_finished(self, ok: bool):
        self.state_mgr.refresh_now(reload_orgs=True)
        if ok:
            self.notify("Pangolin", _("Logged in successfully."))

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
