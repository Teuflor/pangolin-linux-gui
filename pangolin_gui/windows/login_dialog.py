"""GTK 3 dialog for Pangolin device-code login."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk

from typing import Any, Optional
from .. import cli
from pangolin_gui.i18n import _

CLOUD_HOST = "https://app.pangolin.net"


def normalize_host(raw: str) -> str:
    raw = (raw or "").strip().rstrip("/")
    if raw and not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    return raw


class LoginDialog(Gtk.Dialog):
    """Multi-page dialog guiding the user through device-code authentication."""

    def __init__(self, parent: Optional[Gtk.Window] = None, controller: Any = None,
                 host: Optional[str] = None, start: bool = False):
        super().__init__(
            title=_("Log in to Pangolin"),
            transient_for=parent,
            flags=Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT,
        )
        self.controller = controller

        self._session: Optional[cli.LoginSession] = None
        self._code: str = ""
        self._url: str = ""
        self._closed = False

        self.set_default_size(440, 260)
        self.set_resizable(False)

        # Setup pages via Gtk.Stack
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.set_transition_duration(200)

        self._init_page1_host()
        self._init_page2_code()
        self._init_page3_result()

        content_area = self.get_content_area()
        content_area.pack_start(self.stack, True, True, 0)

        # Setup action buttons
        self._cancel_btn = self.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)

        self._action_btn = Gtk.Button(label=_("Next"))
        self._action_btn.get_style_context().add_class("suggested-action")
        self._action_btn.connect("clicked", self._on_action_clicked)
        self.get_action_area().pack_end(self._action_btn, False, False, 0)
        self._action_btn.show()

        self.connect("response", self._on_response)
        self.connect("delete-event", self._on_delete_event)

        self.show_all()
        # Keep inline error label hidden until needed
        self.host_error_label.hide()
        self.connect("destroy", self._on_destroy)

        if host:
            self.prefill_host(host)
            if start:
                self._start_login(normalize_host(host))

    def prefill_host(self, host: str) -> None:
        """Preselect the known server: Cloud radio, or self-hosted with the URL filled in."""
        host = normalize_host(host)
        if host.rstrip("/") == CLOUD_HOST:
            self.radio_cloud.set_active(True)
        else:
            self.radio_self.set_active(True)
            self.host_entry.set_text(host)
            self.host_entry.set_sensitive(True)

    def _on_destroy(self, *_args) -> None:
        self._closed = True
        self._cancel_session()

    def _init_page1_host(self) -> None:
        """Page 1: Radio buttons for hosting option and host entry."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_border_width(18)

        heading = Gtk.Label()
        heading.set_markup(f"<b>{GLib.markup_escape_text(_('Select your Pangolin hosting option'))}</b>")
        heading.set_xalign(0.0)
        box.pack_start(heading, False, False, 0)

        self.radio_cloud = Gtk.RadioButton.new_with_label(
            None, _("Pangolin Cloud (app.pangolin.net)")
        )
        self.radio_self = Gtk.RadioButton.new_with_label_from_widget(
            self.radio_cloud, _("Self-hosted or Dedicated instance")
        )
        box.pack_start(self.radio_cloud, False, False, 0)
        box.pack_start(self.radio_self, False, False, 0)

        self.host_entry = Gtk.Entry()
        self.host_entry.set_placeholder_text("https://your-instance.example.com")
        self.host_entry.set_sensitive(False)
        box.pack_start(self.host_entry, False, False, 0)

        self.host_error_label = Gtk.Label()
        self.host_error_label.set_markup('<span color="#e74c3c" size="small"></span>')
        self.host_error_label.set_xalign(0.0)
        self.host_error_label.set_no_show_all(True)
        box.pack_start(self.host_error_label, False, False, 0)

        def on_radio_toggled(_btn: Gtk.RadioButton) -> None:
            is_self = self.radio_self.get_active()
            self.host_entry.set_sensitive(is_self)
            self.host_error_label.hide()
            if is_self:
                self.host_entry.grab_focus()

        self.radio_cloud.connect("toggled", on_radio_toggled)
        self.radio_self.connect("toggled", on_radio_toggled)
        self.host_entry.connect("activate", lambda _: self._on_action_clicked())

        self.stack.add_named(box, "page_host")

    def _init_page2_code(self) -> None:
        """Page 2: One-time device authorization code, copy/browser buttons, spinner."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.set_border_width(18)

        desc = Gtk.Label(label=_("First copy your one-time code:"))
        desc.set_xalign(0.5)
        box.pack_start(desc, False, False, 0)

        self.code_label = Gtk.Label()
        self.code_label.set_selectable(True)
        self.code_label.set_markup(
            f'<span size="xx-large" weight="bold" font_family="monospace">{GLib.markup_escape_text(_("Generating…"))}</span>'
        )
        box.pack_start(self.code_label, False, False, 0)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        btn_box.set_halign(Gtk.Align.CENTER)

        self.copy_btn = Gtk.Button(label=_("Copy code"))
        self.copy_btn.connect("clicked", self._on_copy_clicked)
        btn_box.pack_start(self.copy_btn, False, False, 0)

        self.browser_btn = Gtk.Button(label=_("Open browser"))
        self.browser_btn.connect("clicked", self._on_browser_clicked)
        btn_box.pack_start(self.browser_btn, False, False, 0)

        box.pack_start(btn_box, False, False, 0)

        spinner_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        spinner_box.set_halign(Gtk.Align.CENTER)
        self.spinner = Gtk.Spinner()
        self.spinner_label = Gtk.Label(label=_("Waiting for confirmation…"))
        spinner_box.pack_start(self.spinner, False, False, 0)
        spinner_box.pack_start(self.spinner_label, False, False, 0)

        box.pack_start(spinner_box, False, False, 0)

        self.stack.add_named(box, "page_code")

    def _init_page3_result(self) -> None:
        """Page 3: Success or error summary."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.set_border_width(18)

        self.result_title = Gtk.Label()
        self.result_title.set_xalign(0.5)
        box.pack_start(self.result_title, False, False, 0)

        self.result_msg = Gtk.Label()
        self.result_msg.set_xalign(0.5)
        self.result_msg.set_line_wrap(True)
        self.result_msg.set_max_width_chars(42)
        box.pack_start(self.result_msg, False, False, 0)

        self.stack.add_named(box, "page_result")

    def _on_action_clicked(self, _widget: Optional[Gtk.Widget] = None) -> None:
        current = self.stack.get_visible_child_name()
        if current == "page_host":
            self._submit_host()
        elif current == "page_result":
            self.destroy()

    def _submit_host(self) -> None:
        if self.radio_cloud.get_active():
            host = CLOUD_HOST
        else:
            raw = self.host_entry.get_text().strip()
            if not raw:
                self.host_error_label.set_markup(
                    f'<span color="#e74c3c" size="small">{GLib.markup_escape_text(_("Please enter a host URL."))}</span>'
                )
                self.host_error_label.show()
                self.host_entry.grab_focus()
                return

            host = normalize_host(raw)

        self.host_error_label.hide()
        self._start_login(host)

    def _start_login(self, host: str) -> None:
        self.stack.set_visible_child_name("page_code")
        self._action_btn.hide()
        self.spinner.start()
        self.spinner_label.set_text(_("Waiting for confirmation…"))

        self._session = cli.LoginSession(
            host=host,
            on_code=self._on_code_bg,
            on_done=self._on_done_bg,
        )
        self._session.start()

    def _on_copy_clicked(self, _widget: Optional[Gtk.Widget] = None) -> None:
        if self._code:
            clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            clipboard.set_text(self._code, -1)

    def _on_browser_clicked(self, _widget: Optional[Gtk.Widget] = None) -> None:
        if not self._url:
            return

        if self.controller and hasattr(self.controller, "open_url"):
            try:
                self.controller.open_url(self._url)
                return
            except Exception:
                pass

        try:
            Gtk.show_uri_on_window(self, self._url, Gdk.CURRENT_TIME)
        except Exception:
            import webbrowser

            webbrowser.open(self._url)

    def _on_code_bg(self, code: str, url: str) -> None:
        GLib.idle_add(self._apply_code, code, url)

    def _apply_code(self, code: str, url: str) -> bool:
        if self._closed:
            return False
        self._code = code
        self._url = url
        escaped = GLib.markup_escape_text(code)
        self.code_label.set_markup(
            f'<span size="xx-large" weight="bold" font_family="monospace">{escaped}</span>'
        )
        return False

    def _on_done_bg(self, ok: bool, message: str) -> None:
        GLib.idle_add(self._apply_done, ok, message)

    def _apply_done(self, ok: bool, message: str) -> bool:
        if self._closed:
            return False
        self.spinner.stop()
        self._session = None
        self.stack.set_visible_child_name("page_result")

        if ok:
            self.result_title.set_markup(
                f'<span size="x-large" weight="bold" color="#2ecc71">{GLib.markup_escape_text(_("Login Successful"))}</span>'
            )
            self.result_msg.set_text(message or _("Device authorized successfully."))
        else:
            self.result_title.set_markup(
                f'<span size="x-large" weight="bold" color="#e74c3c">{GLib.markup_escape_text(_("Login Failed"))}</span>'
            )
            self.result_msg.set_text(message or _("Authentication was not completed."))

        self._cancel_btn.hide()
        self._action_btn.set_label(_("Close"))
        self._action_btn.show()

        if self.controller and hasattr(self.controller, "on_login_finished"):
            try:
                self.controller.on_login_finished(ok)
            except Exception:
                pass

        return False

    def _on_response(self, _dialog: Gtk.Dialog, response_id: int) -> None:
        if response_id == Gtk.ResponseType.CANCEL:
            self._cancel_session()
            self.destroy()

    def _on_delete_event(self, _widget: Gtk.Widget, _event: Gdk.Event) -> bool:
        self._cancel_session()
        return False

    def _cancel_session(self) -> None:
        if self._session:
            try:
                self._session.cancel()
            except Exception:
                pass
            self._session = None
