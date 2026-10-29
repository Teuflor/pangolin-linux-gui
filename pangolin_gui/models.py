"""Shared data models. Every module exchanges these types; do not add GTK imports here."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ConnState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"        # up started, not yet registered
    CONNECTED = "connected"          # connected and registered
    DISCONNECTING = "disconnecting"
    ERROR = "error"


@dataclass
class Peer:
    site_id: int
    name: str
    connected: bool
    rtt_ms: float                    # olm reports Go time.Duration in nanoseconds; converted to ms
    last_seen: Optional[str]         # ISO-8601 string as delivered by olm, or None
    endpoint: str = ""
    is_relay: bool = False
    is_local: bool = False
    peer_address: str = ""


@dataclass
class ExitNodeStatus:
    connected: bool
    rtt_ms: float
    last_seen: Optional[str]
    endpoint: str = ""


@dataclass
class OlmStatus:
    """Parsed GET /status response of the olm daemon."""
    connected: bool = False
    registered: bool = False
    terminated: bool = False
    version: str = ""
    agent: str = ""
    org_id: str = ""
    peers: list[Peer] = field(default_factory=list)
    exit_node: Optional[ExitNodeStatus] = None
    gateway_active: bool = False
    error_code: str = ""
    error_message: str = ""


@dataclass
class Account:
    user_id: str
    host: str                        # e.g. "https://app.pangolin.net"
    email: str
    username: Optional[str] = None
    name: Optional[str] = None
    session_token: str = ""
    org_id: str = ""
    server_version: str = ""
    server_build: str = ""           # "oss" | "enterprise" | "saas"

    @property
    def display_name(self) -> str:
        return self.email or self.username or self.name or self.user_id


@dataclass
class Org:
    org_id: str
    name: str


@dataclass
class OrgClient:
    """Another device/client in the organization (from the REST API)."""
    client_id: int
    name: str
    address: str                     # tunnel IP without prefix length, e.g. "100.90.128.5"
    online: bool
    owner: str = ""                  # user email/username for user devices, "" for machine clients
    is_self: bool = False            # this computer (matched by its tunnel IP)


@dataclass
class OrgSite:
    """A site of the organization (from the REST API), whether or not the tunnel uses it."""
    site_id: int
    name: str
    online: bool


@dataclass
class AppState:
    """Snapshot the UI renders. Produced by state.StateManager."""
    conn: ConnState = ConnState.DISCONNECTED
    status: Optional[OlmStatus] = None
    accounts: list[Account] = field(default_factory=list)
    active_account: Optional[Account] = None
    orgs: list[Org] = field(default_factory=list)
    clients: list[OrgClient] = field(default_factory=list)   # online clients, this device first
    clients_error: str = ""          # "forbidden" when the role may not list clients, else message
    sites: list[OrgSite] = field(default_factory=list)       # tunnel sites of the org (API)
    own_ip: str = ""                 # tunnel IP of this computer while connected
    cli_installed: bool = True
    cli_version: str = ""
    last_error: str = ""
