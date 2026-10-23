"""Optional system service mode: run the tunnel as pangolin-gui@<user>.service.

`install.sh --system-service` installs a systemd template unit, a root-owned start
helper and a polkit rule that lets the user start and stop their own unit without a
password. When that is installed, connecting uses `systemctl start` instead of the
CLI's `sudo` path; otherwise nothing changes.
"""
from __future__ import annotations

import getpass
import logging
import subprocess
import time
from pathlib import Path

from pangolin_gui.i18n import _

log = logging.getLogger(__name__)

UNIT_FILE = Path("/etc/systemd/system/pangolin-gui@.service")
HELPER = Path("/usr/local/lib/pangolin-gui/pangolin-gui-client")
START_TIMEOUT = 10.0


class ServiceError(Exception):
    """systemctl failed. `denied` is True when polkit refused without asking."""

    def __init__(self, message: str, denied: bool = False):
        super().__init__(message)
        self.denied = denied


def unit_name(user: str | None = None) -> str:
    return f"pangolin-gui@{user or getpass.getuser()}.service"


def installed() -> bool:
    """True when the unit and its start helper are installed."""
    return UNIT_FILE.is_file() and HELPER.is_file()


def _systemctl(*args: str, timeout: float = 30.0) -> subprocess.CompletedProcess:
    # --no-ask-password: fail instead of prompting when the polkit rule is missing.
    cmd = ["systemctl", "--no-ask-password", *args]
    log.debug("run: %s", " ".join(cmd))
    try:
        return subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ServiceError(f"systemctl {' '.join(args)}: {exc}") from exc


def _check(proc: subprocess.CompletedProcess) -> None:
    if proc.returncode == 0:
        return
    msg = (proc.stderr or proc.stdout).strip() or f"systemctl exited with {proc.returncode}"
    lower = msg.lower()
    denied = "interactive authentication required" in lower or "access denied" in lower
    raise ServiceError(msg, denied=denied)


def state(unit: str | None = None) -> tuple[str, str]:
    """(ActiveState, SubState) of the unit, e.g. ("active", "running")."""
    proc = _systemctl("show", "--property=ActiveState,SubState", unit or unit_name(), timeout=10.0)
    if proc.returncode != 0:
        return "unknown", ""
    props = dict(line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line)
    return props.get("ActiveState", "unknown"), props.get("SubState", "")


def is_active(unit: str | None = None) -> bool:
    return state(unit)[0] in ("active", "activating", "reloading")


def start(unit: str | None = None) -> None:
    """Start (or restart) the tunnel unit and fail if it does not stay up."""
    unit = unit or unit_name()
    log.info("starting %s", unit)
    _check(_systemctl("restart", unit))
    # Type=simple returns at once; a bad configuration makes the helper exit shortly
    # after, and with Restart=on-failure that shows up as "activating/auto-restart".
    started = time.monotonic()
    while True:
        active, sub = state(unit)
        if active in ("failed", "inactive") or sub == "auto-restart":
            raise ServiceError(_("The tunnel service stopped right after starting. "
                                 "Details: journalctl -u {unit}").format(unit=unit))
        elapsed = time.monotonic() - started
        if (active == "active" and elapsed >= 2.0) or elapsed >= START_TIMEOUT:
            return  # still starting after the timeout: the status poller takes over
        time.sleep(0.5)


def stop(unit: str | None = None) -> None:
    unit = unit or unit_name()
    log.info("stopping %s", unit)
    _check(_systemctl("stop", unit))
