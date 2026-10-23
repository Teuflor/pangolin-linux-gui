"""Log viewer for the Pangolin client log."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from pangolin_gui.i18n import _  # noqa: E402
from pangolin_gui.models import AppState  # noqa: E402

_LEVEL_TAGS = (("error", (" ERROR", "level=error", "[ERROR]")),
               ("warn", (" WARN", "level=warn", "[WARN]")),
               ("debug", (" DEBUG", "level=debug", "[DEBUG]")))


def line_tag(line: str) -> str | None:
    for tag, needles in _LEVEL_TAGS:
        if any(n in line for n in needles):
            return tag
    return None


class LogsWindow(Gtk.Window):
    def __init__(self, controller):
        super().__init__(title=_("Pangolin Logs"))
        self.controller = controller
        self._timer_id = None
        self._loading = False
        self._last_text = None
        self.set_default_size(800, 500)
        self.set_icon_name("network-vpn")
        self.connect("delete-event", self._on_delete)
        self.connect("show", lambda *_: self._on_visibility(True))
        self.connect("hide", lambda *_: self._on_visibility(False))

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, border_width=8)
        self.add(root)

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        root.pack_start(bar, False, False, 0)
        refresh = Gtk.Button(label=_("Refresh"))
        refresh.connect("clicked", lambda *_: self.refresh())
        bar.pack_start(refresh, False, False, 0)
        self.auto_check = Gtk.CheckButton(label=_("Auto-refresh"), active=True)
        self.auto_check.connect("toggled", lambda *_: self._on_visibility(self.get_visible()))
        bar.pack_start(self.auto_check, False, False, 0)
        self.follow_check = Gtk.CheckButton(label=_("Follow"), active=True)
        bar.pack_start(self.follow_check, False, False, 0)
        copy = Gtk.Button(label=_("Copy all"))
        copy.connect("clicked", self._on_copy)
        bar.pack_start(copy, False, False, 0)
        self.search = Gtk.SearchEntry(placeholder_text=_("Search"))
        self.search.connect("search-changed", lambda *_: self._highlight())
        bar.pack_end(self.search, False, False, 0)

        self.buffer = Gtk.TextBuffer()
        self.buffer.create_tag("match", background="#fde047", foreground="#000000")
        self.buffer.create_tag("error", foreground="#ef4444")
        self.buffer.create_tag("warn", foreground="#f97316")
        self.buffer.create_tag("debug", foreground="#9ca3af")
        self.buffer.set_text(_("Loading…"))
        self.view = Gtk.TextView(buffer=self.buffer, editable=False, monospace=True,
                                 cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_shadow_type(Gtk.ShadowType.IN)
        scroller.add(self.view)
        root.pack_start(scroller, True, True, 0)

    def _on_delete(self, *_):
        self.hide()
        return True

    def present_window(self):
        self.show_all()
        self.present()
        self.refresh()

    def update(self, state: AppState):
        pass

    def _on_visibility(self, visible: bool):
        want_timer = visible and self.auto_check.get_active()
        if want_timer and self._timer_id is None:
            self._timer_id = GLib.timeout_add_seconds(3, self._tick)
        elif not want_timer and self._timer_id is not None:
            GLib.source_remove(self._timer_id)
            self._timer_id = None

    def _tick(self):
        self.refresh()
        return True

    def refresh(self):
        if self._loading:
            return
        self._loading = True
        # controller.read_logs runs the CLI in a worker thread and calls back from it
        self.controller.read_logs(lambda text: GLib.idle_add(self._set_text, text))

    def _set_text(self, text: str):
        self._loading = False
        if text == self._last_text:
            return False
        self._last_text = text
        self.buffer.set_text(text or _("(log is empty)"))
        if not text.startswith("ERROR:"):
            for n, line in enumerate(text.splitlines()):
                tag = line_tag(line)
                if tag:
                    start = self.buffer.get_iter_at_line(n)
                    end = start.copy()
                    end.forward_to_line_end()
                    self.buffer.apply_tag_by_name(tag, start, end)
        self._highlight()
        if self.follow_check.get_active():
            self.view.scroll_to_mark(self.buffer.get_insert(), 0.0, False, 0.0, 1.0)
            GLib.idle_add(self._scroll_end)
        return False

    def _scroll_end(self):
        self.view.scroll_to_iter(self.buffer.get_end_iter(), 0.0, False, 0.0, 1.0)
        return False

    def _highlight(self):
        start, end = self.buffer.get_bounds()
        self.buffer.remove_tag_by_name("match", start, end)
        needle = self.search.get_text()
        if not needle:
            return
        it = self.buffer.get_start_iter()
        while True:
            found = it.forward_search(needle, Gtk.TextSearchFlags.CASE_INSENSITIVE, None)
            if not found:
                break
            self.buffer.apply_tag_by_name("match", *found)
            it = found[1]

    def _on_copy(self, *_):
        start, end = self.buffer.get_bounds()
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(self.buffer.get_text(start, end, False), -1)
