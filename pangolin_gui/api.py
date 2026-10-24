"""Minimal client for the Pangolin REST API (session-cookie auth, like the CLI)."""
from __future__ import annotations

import json
import logging
import ssl
import urllib.error
import urllib.request
from urllib.parse import quote, urlencode

from pangolin_gui.models import Account, Org, OrgClient, OrgSite

log = logging.getLogger(__name__)


class ApiError(Exception):
    """API call failed. `auth_expired` is True for HTTP 401, `forbidden` for HTTP 403."""

    def __init__(self, message: str, auth_expired: bool = False, forbidden: bool = False):
        super().__init__(message)
        self.auth_expired = auth_expired
        self.forbidden = forbidden


def strip_prefix(subnet: str | None) -> str:
    """"100.90.128.5/32" -> "100.90.128.5"."""
    return (subnet or "").split("/")[0].strip()


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

        log.debug("%s %s -> HTTP %s", method, path.split("?")[0], status)
        if status >= 400 or not body.get("success", False):
            msg = body.get("message") or (body.get("error") if isinstance(body.get("error"), str) else "")
            raise ApiError(msg or f"HTTP {status}", auth_expired=status == 401, forbidden=status == 403)
        return body.get("data") or {}

    def list_online_clients(self, org_id: str) -> list[OrgClient]:
        """Online clients of an org: machine clients plus user devices, deduplicated.

        Both endpoints need the `listClients` permission (usually admins). If both
        are forbidden, ApiError(forbidden=True) is raised.
        """
        org = quote(org_id, safe="")
        query = urlencode({"online": "true", "pageSize": 200})
        found: dict[int, OrgClient] = {}
        forbidden = 0
        for path, key in ((f"/org/{org}/clients?{query}", "clients"),
                          (f"/org/{org}/user-devices?{query}", "devices")):
            try:
                data = self._request("GET", path)
            except ApiError as exc:
                if exc.forbidden:
                    forbidden += 1
                    continue
                raise
            for item in data.get(key) or []:
                client = _parse_client(item)
                if client and client.online and client.client_id not in found:
                    found[client.client_id] = client
        if forbidden == 2:
            raise ApiError("forbidden", forbidden=True)
        return sorted(found.values(), key=lambda c: (c.name.lower(), c.address))

    def list_orgs(self) -> list[Org]:
        data = self._request("GET", f"/user/{quote(self._account.user_id, safe='')}/orgs")
        orgs = [Org(org_id=o["orgId"], name=o.get("name") or o["orgId"])
                for o in data.get("orgs") or []]
        return sorted(orgs, key=lambda o: o.name.lower())

    def list_sites(self, org_id: str) -> list[OrgSite]:
        """Tunnel sites of an org. The server's own "local" site is skipped: clients never
        connect to it."""
        query = urlencode({"pageSize": 200})
        data = self._request("GET", f"/org/{quote(org_id, safe='')}/sites?{query}")
        sites = []
        for item in data.get("sites") or []:
            try:
                site_id = int(item.get("siteId"))
            except (TypeError, ValueError):
                continue
            if item.get("type") == "local" or item.get("archived"):
                continue
            sites.append(OrgSite(site_id=site_id, name=item.get("name") or item.get("niceId") or f"#{site_id}",
                                 online=bool(item.get("online"))))
        return sorted(sites, key=lambda s: s.name.lower())


def _parse_client(item: dict) -> OrgClient | None:
    try:
        client_id = int(item.get("clientId"))
    except (TypeError, ValueError):
        return None
    address = strip_prefix(item.get("subnet"))
    if not address or item.get("blocked") or item.get("archived"):
        return None
    return OrgClient(
        client_id=client_id,
        name=item.get("name") or item.get("niceId") or f"#{client_id}",
        address=address,
        online=bool(item.get("online")),
        owner=item.get("userEmail") or item.get("email") or item.get("username") or "",
    )
