"""GTK tray backend: AyatanaAppIndicator3 / AppIndicator3, or Gtk.StatusIcon on X11.

AppIndicator has a single menu for every click, so the status window is reachable
via the "Open Status…" entry and the middle click (secondary activate target).
Gtk.StatusIcon (X11 only) opens the status window on left click.
"""
from __future__ import annotations

import logging
import pathlib
from typing import Callable, Optional

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from pangolin_gui.menu_model import CHECK, LABEL, RADIO, SEPARATOR, MenuNode  # noqa: E402

log = logging.getLogger(__name__)


def _load_indicator():
    for name in ("AyatanaAppIndicator3", "AppIndicator3"):
        try:
            gi.require_version(name, "0.1")
            module = __import__("gi.repository", fromlist=[name])
            return getattr(module, name)
        except (ImportError, ValueError, AttributeError):
            continue
    return None


def build_gtk_menu(nodes: list[MenuNode], widgets: dict[str, Gtk.MenuItem] | None = None) -> Gtk.Menu:
    """Render menu nodes into a Gtk.Menu. `widgets` collects id -> item for later lookups."""
    menu = Gtk.Menu()
    radio_group: Optional[Gtk.RadioMenuItem] = None
    for node in nodes:
        if node.kind == SEPARATOR:
            menu.append(Gtk.SeparatorMenuItem())
            radio_group = None
            continue
        if node.kind == RADIO:
            item = Gtk.RadioMenuItem.new_with_label_from_widget(radio_group, node.label)
            radio_group = item
            item.set_active(node.checked)
        else:
            radio_group = None
            if node.kind == CHECK:
                item = Gtk.CheckMenuItem(label=node.label)
                item.set_active(node.checked)
            else:
                item = Gtk.MenuItem(label=node.label)
        item.set_use_underline(False)
        item.set_sensitive(node.enabled and node.kind != LABEL)
        if node.tooltip:
            item.set_tooltip_text(node.tooltip)
        if node.children:
            item.set_submenu(build_gtk_menu(node.children, widgets))
        elif node.action is not None:
            # "activate" fires once per click (unlike "toggled" on radio groups)
            item.connect("activate", lambda _w, act=node.action: act())
        if widgets is not None:
            widgets[node.id] = item
        menu.append(item)
    return menu


class GtkTrayBackend:
    def __init__(self, icon_dir: pathlib.Path, on_activate: Callable[[], None]):
        self.icon_dir = pathlib.Path(icon_dir)
        self._on_activate = on_activate
        self._menu: Optional[Gtk.Menu] = None
        self._indicator = None
        self._status_icon = None
        indicator_mod = _load_indicator()
        if indicator_mod is not None:
            self._indicator = indicator_mod.Indicator.new(
                "pangolin-gui", self._icon_path(False) or "network-vpn",
                indicator_mod.IndicatorCategory.APPLICATION_STATUS)
            self._indicator.set_status(indicator_mod.IndicatorStatus.ACTIVE)
            self._indicator.set_title("Pangolin")
            log.info("tray: AppIndicator (%s)", indicator_mod.__name__)
        else:
            self._status_icon = Gtk.StatusIcon()
            self._status_icon.connect("activate", lambda *_a: self._on_activate())
            self._status_icon.connect("popup-menu", self._on_popup)
            log.info("tray: Gtk.StatusIcon (X11 only)")
        self.set_icon(False)

    def _icon_path(self, connected: bool) -> str:
        path = self.icon_dir / ("pangolin-orange.png" if connected else "pangolin-gray.png")
        return str(path) if path.is_file() else ""

    def set_menu(self, nodes: list[MenuNode]) -> None:
        widgets: dict[str, Gtk.MenuItem] = {}
        self._menu = build_gtk_menu(nodes, widgets)
        self._menu.show_all()
        if self._indicator is not None:
            self._indicator.set_menu(self._menu)
            target = widgets.get("open_status")
            if target is not None:  # middle click opens the status window
                self._indicator.set_secondary_activate_target(target)

    def set_icon(self, connected: bool) -> None:
        path = self._icon_path(connected)
        if self._indicator is not None:
            self._indicator.set_icon_full(path or "network-vpn", "Pangolin")
        elif self._status_icon is not None:
            if path:
                self._status_icon.set_from_file(path)
            else:
                self._status_icon.set_from_icon_name("network-vpn")

    def set_tooltip(self, title: str, text: str) -> None:
        if self._indicator is not None:
            self._indicator.set_title(f"{title}: {text}")
        elif self._status_icon is not None:
            self._status_icon.set_tooltip_text(f"{title}: {text}")

    def close(self) -> None:
        if self._status_icon is not None:
            self._status_icon.set_visible(False)

    def _on_popup(self, icon, button, activate_time):
        if self._menu is not None:
            self._menu.popup(None, None, Gtk.StatusIcon.position_menu, icon, button, activate_time)
