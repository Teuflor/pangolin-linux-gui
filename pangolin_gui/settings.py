"""GUI-only settings (~/.config/pangolin-gui/settings.json) and XDG autostart."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


def _xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path(os.environ.get("HOME") or Path.home()) / ".config")


def settings_path() -> Path:
    return _xdg_config_home() / "pangolin-gui" / "settings.json"


def autostart_path() -> Path:
    return _xdg_config_home() / "autostart" / "pangolin-gui.desktop"


@dataclass
class GuiSettings:
    connect_on_start: bool = False

    @classmethod
    def load(cls) -> "GuiSettings":
        try:
            data = json.loads(settings_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def save(self) -> None:
        path = settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")


def launcher_command() -> str:
    """Command line that starts this app, for the autostart entry."""
    script = Path(sys.argv[0]).resolve()
    if script.name == "pangolin-gui" and os.access(script, os.X_OK):
        return f'"{script}" --hidden'
    return f'{sys.executable} -m pangolin_gui --hidden'


def autostart_enabled() -> bool:
    return autostart_path().is_file()


def set_autostart(enabled: bool) -> None:
    path = autostart_path()
    if not enabled:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Pangolin\n"
        "Comment=Pangolin tray client\n"
        f"Exec={launcher_command()}\n"
        "Icon=network-vpn\n"
        "X-GNOME-Autostart-enabled=true\n"
        "Terminal=false\n",
        encoding="utf-8",
    )
