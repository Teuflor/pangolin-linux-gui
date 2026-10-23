"""HTTP-over-Unix-socket client for the Pangolin olm daemon."""
from __future__ import annotations

import json
import os
import socket
from http.client import HTTPConnection
from typing import Optional

from pangolin_gui.models import ExitNodeStatus, OlmStatus, Peer

SOCKET_PATH = "/var/run/olm.sock"
_GO_ZERO_TIME = "0001-01-01T00:00:00Z"


class OlmError(Exception):
    """Raised on any olm socket / HTTP failure."""


class _UnixHttpConnection(HTTPConnection):
    """HTTPConnection that talks over an AF_UNIX socket instead of TCP."""

    def __init__(self, socket_path: str, timeout: float = 3.0):
        super().__init__("localhost", timeout=timeout)
        self._socket_path = socket_path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._socket_path)


def _rtt_ms(value) -> float:
    return round(value / 1e6, 1) if isinstance(value, (int, float)) else 0.0


def _last_seen(value) -> Optional[str]:
    return None if value in (None, "", _GO_ZERO_TIME) else value


def parse_status(data: dict) -> OlmStatus:
    """Pure function: raw JSON dict -> OlmStatus. No I/O."""
    peers: list[Peer] = []
    for site_id_str, pd in (data.get("peers") or {}).items():
        try:
            site_id = int(pd.get("siteId", site_id_str))
        except (ValueError, TypeError):
            site_id = 0
        peers.append(Peer(
            site_id=site_id,
            name=pd.get("name", ""),
            connected=bool(pd.get("connected", False)),
            rtt_ms=_rtt_ms(pd.get("rtt", 0)),
            last_seen=_last_seen(pd.get("lastSeen")),
            endpoint=pd.get("endpoint", ""),
            is_relay=bool(pd.get("isRelay", False)),
            is_local=bool(pd.get("isLocal", False)),
            peer_address=pd.get("peerAddress", ""),
        ))
    peers.sort(key=lambda p: p.name.lower())

    exit_node: Optional[ExitNodeStatus] = None
    en = data.get("exitNode")
    if en:
        exit_node = ExitNodeStatus(
            connected=bool(en.get("connected", False)),
            rtt_ms=_rtt_ms(en.get("rtt", 0)),
            last_seen=_last_seen(en.get("lastSeen")),
            endpoint=en.get("endpoint", ""),
        )

    err = data.get("error") or {}
    return OlmStatus(
        connected=bool(data.get("connected", False)),
        registered=bool(data.get("registered", False)),
        terminated=bool(data.get("terminated", False)),
        version=data.get("version", ""),
        agent=data.get("agent", ""),
        org_id=data.get("orgId", ""),
        peers=peers,
        exit_node=exit_node,
        gateway_active=bool(data.get("gatewayActive", False)),
        error_code=err.get("code", ""),
        error_message=err.get("message", ""),
    )


class OlmClient:
    """Client for the Pangolin olm daemon over a Unix domain socket."""

    def __init__(self, socket_path: str = SOCKET_PATH, timeout: float = 3.0):
        self.socket_path = socket_path
        self.timeout = timeout

    def _request(self, method: str, path: str, body: bytes | None = None,
                 headers: dict[str, str] | None = None) -> dict:
        conn = _UnixHttpConnection(self.socket_path, self.timeout)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            resp = conn.getresponse()
            status, raw = resp.status, resp.read()
        except FileNotFoundError:
            raise OlmError("Pangolin client is not running") from None
        except PermissionError:
            raise OlmError(f"No permission to access {self.socket_path}") from None
        except ConnectionRefusedError:
            raise OlmError("Pangolin client is not running") from None
        except OSError as exc:
            raise OlmError(f"Cannot talk to {self.socket_path}: {exc}") from None
        finally:
            conn.close()
        if status not in (200, 202):
            raise OlmError(f"HTTP {status} from {path}: {raw[:200].decode(errors='replace')}")
        try:
            return json.loads(raw) if raw else {}
        except ValueError as exc:
            raise OlmError(f"Invalid JSON response: {exc}") from None

    def is_running(self) -> bool:
        if not os.path.exists(self.socket_path):
            return False
        try:
            self.get_status()
            return True
        except OlmError:
            return False

    def get_status(self) -> OlmStatus:
        return parse_status(self._request("GET", "/status"))

    def exit(self) -> None:
        self._request("POST", "/exit")

    def switch_org(self, org_id: str) -> None:
        body = json.dumps({"org_id": org_id}).encode("utf-8")
        self._request("POST", "/switch-org", body=body,
                      headers={"Content-Type": "application/json"})
