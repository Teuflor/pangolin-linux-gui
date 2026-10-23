"""Preferences window: GUI behaviour plus the CLI's `up.*` connection settings."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from pangolin_gui import accounts, settings  # noqa: E402
from pangolin_gui.models import AppState  # noqa: E402

# (config key, label, kind) – keys from `pangolin config list`
CLI_OPTIONS = [
    ("up.tunnel_dns", "Send DNS queries through the tunnel", "bool"),
    ("up.override_dns", "Override system DNS while connected", "bool"),
    ("up.prefer_local_routes", "Prefer local routes when available", "bool"),
    ("up.exit_node_takes_precedence", "Send all traffic through the exit node", "bool"),
    ("up.upstream_dns", "Upstream DNS servers", "list"),
    ("up.match_domains_dns", "Only resolve these domains via Pangolin", "list"),
    ("log_level", "Log level", "choice"),
]
LOG_LEVELS = ["debug", "info", "warn", "error"]


def get_nested(cfg: dict, key: str):
    node = cfg
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def format_value(kind: str, value) -> str:
    if kind == "bool":
        return "true" if value else "false"
    if kind == "list":
        if isinstance(value, str):
            items = value.split(",")
        else:
            items = value or []
        return ",".join(s.strip() for s in items if s and s.strip())
    return str(value or "")


class PreferencesWindow(Gtk.Window):
    def __init__(self, controller):
        super().__init__(title="Pangolin Preferences")
        self.controller = controller
        self.set_default_size(520, -1)
        self.set_resizable(False)
        self.set_icon_name("network-vpn")
        self.connect("delete-event", self._on_delete)
        self._widgets: dict[str, tuple[str, Gtk.Widget]] = {}
        self._initial: dict[str, str] = {}

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, border_width=16)
        self.add(root)

        root.pack_start(self._heading("General"), False, False, 0)
        self.autostart = Gtk.CheckButton(label="Start Pangolin when I log in")
        self.connect_on_start = Gtk.CheckButton(label="Connect automatically when Pangolin starts")
        root.pack_start(self.autostart, False, False, 0)
        root.pack_start(self.connect_on_start, False, False, 0)

        root.pack_start(self._heading("Connection"), False, False, 0)
        grid = Gtk.Grid(column_spacing=12, row_spacing=8)
        root.pack_start(grid, False, False, 0)
        row = 0
        for key, label, kind in CLI_OPTIONS:
            if kind == "bool":
                widget = Gtk.CheckButton(label=label)
                grid.attach(widget, 0, row, 2, 1)
            else:
                grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
                if kind == "choice":
                    widget = Gtk.ComboBoxText()
                    for level in LOG_LEVELS:
                        widget.append(level, level)
                else:
                    widget = Gtk.Entry(hexpand=True, placeholder_text="comma separated")
                grid.attach(widget, 1, row, 1, 1)
            self._widgets[key] = (kind, widget)
            row += 1

        note = Gtk.Label(label="Connection settings apply the next time you connect.", xalign=0)
        note.get_style_context().add_class("dim-label")
        root.pack_start(note, False, False, 0)

        self.error_label = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.error_label.set_no_show_all(True)
        root.pack_start(self.error_label, False, False, 0)

        buttons = Gtk.Box(spacing=6, halign=Gtk.Align.END)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.hide())
        self.save_button = Gtk.Button(label="Save")
        self.save_button.get_style_context().add_class("suggested-action")
        self.save_button.connect("clicked", self._on_save)
        buttons.pack_start(cancel, False, False, 0)
        buttons.pack_start(self.save_button, False, False, 0)
        root.pack_end(buttons, False, False, 0)

    @staticmethod
    def _heading(text: str) -> Gtk.Label:
        label = Gtk.Label(xalign=0)
        label.set_markup(f"<b>{text}</b>")
        return label

    def _on_delete(self, *_):
        self.hide()
        return True

    def present_window(self):
        self._load()
        self.show_all()
        self.present()

    def update(self, state: AppState):
        pass

    def _load(self):
        self.error_label.hide()
        self.save_button.set_sensitive(True)
        self.autostart.set_active(settings.autostart_enabled())
        self.connect_on_start.set_active(settings.GuiSettings.load().connect_on_start)
        cfg = accounts.load_config()
        self._initial = {}
        for key, (kind, widget) in self._widgets.items():
            value = get_nested(cfg, key)
            if kind == "bool":
                widget.set_active(bool(value))
            elif kind == "choice":
                widget.set_active_id(value if value in LOG_LEVELS else "info")
            else:
                widget.set_text(format_value("list", value).replace(",", ", "))
            self._initial[key] = self._current(kind, widget)

    @staticmethod
    def _current(kind: str, widget: Gtk.Widget) -> str:
        if kind == "bool":
            return format_value("bool", widget.get_active())
        if kind == "choice":
            return widget.get_active_id() or "info"
        return format_value("list", widget.get_text())

    def _on_save(self, *_):
        settings.set_autostart(self.autostart.get_active())
        gui = settings.GuiSettings.load()
        gui.connect_on_start = self.connect_on_start.get_active()
        gui.save()

        changes = {}
        for key, (kind, widget) in self._widgets.items():
            value = self._current(kind, widget)
            if value != self._initial.get(key):
                changes[key] = value
        if not changes:
            self.hide()
            return
        self.save_button.set_sensitive(False)
        self.controller.apply_cli_config(changes, self._on_saved)

    def _on_saved(self, error: str | None):
        """Called on the GTK thread by the controller."""
        self.save_button.set_sensitive(True)
        if error:
            self.error_label.set_markup(f"<span color='#ef4444'>{_escape(error)}</span>")
            self.error_label.show()
        else:
            self.hide()


def _escape(text: str) -> str:
    from gi.repository import GLib
    return GLib.markup_escape_text(text)
