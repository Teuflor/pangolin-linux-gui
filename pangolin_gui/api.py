"""Minimal client for the Pangolin REST API (session-cookie auth, like the CLI)."""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from urllib.parse import quote

from pangolin_gui.models import Account, Org


class ApiError(Exception):
    """API call failed. `auth_expired` is True for HTTP 401/403."""

    def __init__(self, message: str, auth_expired: bool = False):
        super().__init__(message)
        self.auth_expired = auth_expired


def build_base_url(host: str) -> str:
    host = host.rstrip("/")
    if host.endswith("/api/v1"):
        return host
    return host + "/api/v1"


class PangolinApi:
    def __init__(self, account: Account, timeout: float = 10.0):
        self._account = account
        self._timeout = timeout
        self.base_url = build_base_url(account.host)

    def _request(self, method: str, path: str):
        req = urllib.request.Request(self.base_url + path, method=method, headers={
            "Cookie": f"p_session_token={self._account.session_token}",
            "X-CSRF-Token": "x-csrf-protection",
            "Accept": "application/json",
            "User-Agent": "pangolin-linux-gui",
        })
        try:
            with urllib.request.urlopen(req, timeout=self._timeout,
                                        context=ssl.create_default_context()) as resp:
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read() or b""
        except (urllib.error.URLError, OSError) as exc:
            raise ApiError(f"Cannot reach {self._account.host}: {exc}") from None

        try:
            body = json.loads(raw) if raw else {}
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}

        if status >= 400 or not body.get("success", False):
            msg = body.get("message") or (body.get("error") if isinstance(body.get("error"), str) else "")
            raise ApiError(msg or f"HTTP {status}", auth_expired=status in (401, 403))
        return body.get("data") or {}

    def list_orgs(self) -> list[Org]:
        data = self._request("GET", f"/user/{quote(self._account.user_id, safe='')}/orgs")
        orgs = [Org(org_id=o["orgId"], name=o.get("name") or o["orgId"])
                for o in data.get("orgs") or []]
        return sorted(orgs, key=lambda o: o.name.lower())
