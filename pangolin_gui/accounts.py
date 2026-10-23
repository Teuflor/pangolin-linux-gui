"""Read Pangolin CLI config files (accounts.json, config.json)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from pangolin_gui.models import Account


def config_dir() -> Path:
    """Return ~/.config/pangolin, respecting the HOME env var."""
    home = os.environ.get("HOME") or str(Path.home())
    return Path(home) / ".config" / "pangolin"


def _read_json(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def load_accounts(path: Path | None = None) -> tuple[list[Account], Account | None]:
    """Parse accounts.json. Returns (sorted_accounts, active_account_or_None)."""
    data = _read_json(path or config_dir() / "accounts.json")
    if data is None:
        return [], None

    accounts: list[Account] = []
    for user_id, info in (data.get("accounts") or {}).items():
        if not isinstance(info, dict):
            continue
        server_info = info.get("serverInfo") or {}
        accounts.append(Account(
            user_id=info.get("userId") or user_id,
            host=info.get("host", ""),
            email=info.get("email", ""),
            username=info.get("username") or None,
            name=info.get("name") or None,
            session_token=info.get("sessionToken", ""),
            org_id=info.get("orgId", ""),
            server_version=server_info.get("version", ""),
            server_build=server_info.get("build", ""),
        ))
    accounts.sort(key=lambda a: a.display_name.lower())

    # The CLI writes "activeuserid"; accept the camelCase spelling too.
    active_id = data.get("activeuserid") or data.get("activeUserId") or ""
    active = next((a for a in accounts if a.user_id == active_id), None)
    return accounts, active


def load_config(path: Path | None = None) -> dict:
    """Parse config.json. Returns {} on missing/invalid file."""
    return _read_json(path or config_dir() / "config.json") or {}
