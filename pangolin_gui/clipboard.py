"""Copy text to the desktop clipboard from a tray app.

A tray menu click arrives over D-Bus, so the app has no keyboard focus. Wayland
compositors refuse clipboard requests from unfocused GTK clients, therefore
wl-copy (Wayland) or xclip/xsel (X11) are preferred when installed.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess

log = logging.getLogger(__name__)


def _commands() -> list[list[str]]:
    cmds = []
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy"):
        cmds.append(["wl-copy"])
    if os.environ.get("DISPLAY"):
        if shutil.which("xclip"):
            cmds.append(["xclip", "-selection", "clipboard"])
        if shutil.which("xsel"):
            cmds.append(["xsel", "--clipboard", "--input"])
    return cmds


def copy_text(text: str) -> bool:
    """Put text on the clipboard. Returns True if a method reported success."""
    for cmd in _commands():
        try:
            # wl-copy/xclip fork a background owner process; don't wait on its stdout
            subprocess.run(cmd, input=text.encode(), check=True, timeout=3,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           start_new_session=True)
            return True
        except (OSError, subprocess.SubprocessError) as exc:
            log.debug("clipboard via %s failed: %s", cmd[0], exc)
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        from gi.repository import Gdk, Gtk
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(text, -1)
        clipboard.store()  # keep the content after the menu closes
        return True
    except Exception as exc:  # no display, no GTK
        log.warning("clipboard unavailable: %s", exc)
        return False
