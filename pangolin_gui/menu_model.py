"""Toolkit-independent tray menu description.

tray.build_menu_model() turns an AppState into a list of MenuNode. Backends render it:
  - tray_gtk  (AppIndicator / Gtk.StatusIcon): converts to Gtk.Menu
  - sni       (StatusNotifierItem + com.canonical.dbusmenu over D-Bus)
No GTK imports here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterator, Optional, Protocol

NORMAL = "normal"        # clickable item
SEPARATOR = "separator"
CHECK = "check"          # checkmark item; `checked` shows the state, click calls `action`
RADIO = "radio"          # radio item inside a group of siblings
LABEL = "label"          # non-clickable info text (rendered disabled)


@dataclass
class MenuNode:
    id: str                                   # stable, unique within the menu, e.g. "connect", "org:abc"
    label: str = ""
    kind: str = NORMAL
    enabled: bool = True
    checked: bool = False                     # for CHECK / RADIO
    tooltip: str = ""
    icon_name: str = ""                       # optional freedesktop icon name
    children: list["MenuNode"] = field(default_factory=list)   # non-empty -> submenu
    action: Optional[Callable[[], None]] = None                 # called on the GTK main thread


def separator(node_id: str) -> MenuNode:
    return MenuNode(id=node_id, kind=SEPARATOR)


def walk(nodes: list[MenuNode]) -> Iterator[MenuNode]:
    for node in nodes:
        yield node
        yield from walk(node.children)


def signature(nodes: list[MenuNode]) -> tuple:
    """Hashable description of everything visible (not the callbacks)."""
    return tuple((n.id, n.label, n.kind, n.enabled, n.checked, n.tooltip, n.icon_name,
                  signature(n.children)) for n in nodes)


class TrayBackend(Protocol):
    """What tray.TrayIcon needs from a backend."""

    def set_menu(self, nodes: list[MenuNode]) -> None: ...
    def set_icon(self, connected: bool) -> None: ...
    def set_tooltip(self, title: str, text: str) -> None: ...
    def close(self) -> None: ...
