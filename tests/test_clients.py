"""Online-clients feature: API parsing, polling, tray signature, clipboard."""
import json
import os
import socket
import stat
import urllib.error
from io import BytesIO

import pytest

from pangolin_gui import api as api_mod
from pangolin_gui import clipboard, netinfo
from pangolin_gui import state as state_mod
from pangolin_gui.api import ApiError, PangolinApi, strip_prefix
from pangolin_gui.models import Account, AppState, ConnState, OlmStatus, OrgClient, OrgSite
from pangolin_gui.state import StateManager
from pangolin_gui.tray import client_menu_label, clients_signature

ACCOUNT = Account(user_id="u1", host="https://p.example", email="a@example.com",
                  session_token="tok", org_id="org1")


class Resp:
    def __init__(self, payload):
        self.status, self._raw = 200, json.dumps(payload).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def route(monkeypatch, responses, seen=None):
    """responses: path-prefix -> payload dict or HTTP status int."""
    def _open(req, timeout=None, context=None):
        if seen is not None:
            seen.append(req.full_url)
        for prefix, value in responses.items():
            if prefix in req.full_url:
                if isinstance(value, int):
                    raise urllib.error.HTTPError(req.full_url, value, "x", {},
                                                 BytesIO(b'{"success":false,"message":"no"}'))
                return Resp({"success": True, "data": value})
        raise AssertionError(req.full_url)
    monkeypatch.setattr(api_mod.urllib.request, "urlopen", _open)


def test_strip_prefix():
    assert strip_prefix("100.90.128.5/32") == "100.90.128.5"
    assert strip_prefix("100.90.128.5") == "100.90.128.5"
    assert strip_prefix(None) == ""


def test_list_online_clients_merges_and_filters(monkeypatch):
    seen = []
    route(monkeypatch, {
        "/clients?": {"clients": [
            {"clientId": 2, "name": "server-b", "subnet": "100.90.128.9/32", "online": True},
            {"clientId": 3, "name": "blocked", "subnet": "100.90.128.10/32", "online": True, "blocked": True},
            {"clientId": 4, "name": "offline", "subnet": "100.90.128.11/32", "online": False},
        ]},
        "/user-devices?": {"devices": [
            {"clientId": 2, "name": "dup", "subnet": "100.90.128.9/32", "online": True},
            {"clientId": 1, "name": "Anna-Laptop", "subnet": "100.90.128.7/32", "online": True,
             "userEmail": "anna@example.com"},
            {"clientId": 5, "name": "no-ip", "subnet": None, "online": True},
        ]},
    }, seen)
    clients = PangolinApi(ACCOUNT).list_online_clients("org1")
    assert [(c.client_id, c.name, c.address, c.owner) for c in clients] == [
        (1, "Anna-Laptop", "100.90.128.7", "anna@example.com"),
        (2, "server-b", "100.90.128.9", ""),
    ]
    assert all("online=true" in url for url in seen)


def test_list_online_clients_partial_permission(monkeypatch):
    route(monkeypatch, {"/clients?": 403,
                        "/user-devices?": {"devices": [
                            {"clientId": 1, "name": "x", "subnet": "100.90.128.7/32", "online": True}]}})
    assert [c.client_id for c in PangolinApi(ACCOUNT).list_online_clients("org1")] == [1]


def test_list_online_clients_forbidden(monkeypatch):
    route(monkeypatch, {"/clients?": 403, "/user-devices?": 403})
    with pytest.raises(ApiError) as exc:
        PangolinApi(ACCOUNT).list_online_clients("org1")
    assert exc.value.forbidden and not exc.value.auth_expired


# -- polling ------------------------------------------------------------------------

class FakeOlm:
    def __init__(self, status):
        self.status = status

    def is_running(self):
        return self.status is not None

    def get_status(self):
        return self.status


@pytest.fixture
def manager(tmp_path, monkeypatch):
    path = tmp_path / "accounts.json"
    path.write_text(json.dumps({"activeUserId": "u1", "accounts": {"u1": {
        "userId": "u1", "host": "https://p.example", "email": "a@example.com",
        "sessionToken": "tok", "orgId": "org1"}}}))
    calls = []

    class FakeApi:
        result = [OrgClient(1, "me", "100.90.128.2", True), OrgClient(2, "other", "100.90.128.3", True)]
        error = None

        def __init__(self, account):
            pass

        def list_orgs(self):
            return []

        def list_online_clients(self, org_id):
            calls.append(org_id)
            if FakeApi.error:
                raise FakeApi.error
            return list(FakeApi.result)

        sites = [OrgSite(3, "Office", True)]
        sites_error = None

        def list_sites(self, org_id):
            if FakeApi.sites_error:
                raise FakeApi.sites_error
            return list(FakeApi.sites)

    monkeypatch.setattr(state_mod, "PangolinApi", FakeApi)
    monkeypatch.setattr(state_mod.cli, "find_cli", lambda: None)
    monkeypatch.setattr(state_mod.netinfo, "interface_ipv4", lambda *a: "100.90.128.2")
    olm = FakeOlm(OlmStatus(connected=True, registered=True, org_id="org1"))
    seen = []
    return StateManager(seen.append, olm=olm, accounts_path=path), olm, seen, calls, FakeApi


def test_clients_polled_with_this_device_first(manager):
    mgr, olm, seen, calls, _ = manager
    mgr._poll_once()
    assert [(c.name, c.is_self) for c in seen[-1].clients] == [("me", True), ("other", False)]
    assert seen[-1].own_ip == "100.90.128.2"
    mgr._poll_once()
    assert calls == ["org1"]  # throttled to CLIENTS_INTERVAL
    mgr.refresh_now(reload_clients=True)
    mgr._poll_once()
    assert calls == ["org1", "org1"]


def test_clients_cleared_when_disconnected(manager):
    mgr, olm, seen, calls, _ = manager
    mgr._poll_once()
    olm.status = None
    mgr._poll_once()
    assert seen[-1].clients == [] and seen[-1].clients_error == ""


def test_clients_forbidden_reported(manager):
    mgr, olm, seen, calls, FakeApi = manager
    FakeApi.error = ApiError("forbidden", forbidden=True)
    mgr._poll_once()
    # Without permission the API lists nobody, but this device is still shown (own IP copyable)
    assert seen[-1].clients_error == "forbidden"
    assert [(c.name, c.address, c.is_self) for c in seen[-1].clients] == [
        (socket.gethostname(), "100.90.128.2", True)]


def test_sites_loaded_with_clients_and_cleared_when_disconnected(manager):
    mgr, olm, seen, calls, _ = manager
    mgr._poll_once()
    assert [s.name for s in seen[-1].sites] == ["Office"]
    olm.status = None
    mgr._poll_once()
    assert seen[-1].sites == []


def test_sites_error_does_not_hide_clients(manager):
    mgr, olm, seen, calls, FakeApi = manager
    FakeApi.sites_error = ApiError("forbidden", forbidden=True)
    mgr._poll_once()
    assert seen[-1].sites == [] and [c.name for c in seen[-1].clients] == ["me", "other"]


def test_list_sites_skips_local_and_archived(monkeypatch):
    route(monkeypatch, {"/sites?": {"sites": [
        {"siteId": 3, "name": "Office", "online": True, "type": "newt"},
        {"siteId": 2, "name": "Home", "online": True, "type": "newt"},
        {"siteId": 4, "name": "pangolin.example", "online": None, "type": "local"},
        {"siteId": 5, "name": "Old", "online": False, "type": "newt", "archived": True},
    ]}})
    sites = PangolinApi(ACCOUNT).list_sites("org1")
    assert [(s.site_id, s.name, s.online) for s in sites] == [(2, "Home", True), (3, "Office", True)]


# -- tray helpers -------------------------------------------------------------------

def test_clients_signature_only_when_connected():
    clients = [OrgClient(1, "a", "100.90.128.7", True)]
    assert clients_signature(AppState(conn=ConnState.DISCONNECTED, clients=clients)) == ()
    sig = clients_signature(AppState(conn=ConnState.CONNECTED, clients=clients))
    assert sig != clients_signature(AppState(conn=ConnState.CONNECTED, clients=[]))
    assert client_menu_label(clients[0]) == "a  ·  100.90.128.7"


# -- clipboard / netinfo ------------------------------------------------------------

def test_clipboard_prefers_wl_copy(tmp_path, monkeypatch):
    out = tmp_path / "clip.txt"
    tool = tmp_path / "wl-copy"
    tool.write_text(f"#!/bin/sh\ncat > {out}\n")
    tool.chmod(tool.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.delenv("DISPLAY", raising=False)
    assert clipboard.copy_text("100.90.128.7") is True
    assert out.read_text() == "100.90.128.7"


def test_interface_ipv4_missing_interface():
    assert netinfo.interface_ipv4("nonexistent0") == ""
    assert netinfo.interface_ipv4("lo") == "127.0.0.1"


def test_manual_refresh_right_after_boot(manager, monkeypatch):
    """Regression: refresh was ignored while system uptime (monotonic clock) < 30 s."""
    mgr, olm, seen, calls, _ = manager
    clock = [5.0]
    monkeypatch.setattr(state_mod.time, "monotonic", lambda: clock[0])
    mgr._poll_once()
    mgr.refresh_now(reload_clients=True)
    mgr._poll_once()
    assert calls == ["org1", "org1"]
    clock[0] += 31
    mgr._poll_once()
    assert len(calls) == 3


# -- own IP / this device -------------------------------------------------------------

def test_with_self_marks_and_orders():
    from pangolin_gui.state import with_self
    api = [OrgClient(2, "other", "100.90.128.3", True), OrgClient(1, "laptop", "100.90.128.2", True)]
    result = with_self(api, "100.90.128.2", "host")
    assert [(c.name, c.is_self) for c in result] == [("laptop", True), ("other", False)]
    assert not api[1].is_self  # input list not mutated
    synthetic = with_self([], "100.90.128.9", "my-pc")
    assert [(c.client_id, c.name, c.address, c.is_self) for c in synthetic] == [(0, "my-pc", "100.90.128.9", True)]
    assert with_self(api, "", "host") == api  # unknown own IP: list unchanged


def test_own_ip_cleared_when_disconnected(manager):
    mgr, olm, seen, calls, _ = manager
    mgr._poll_once()
    olm.status = None
    mgr._poll_once()
    assert seen[-1].own_ip == "" and seen[-1].clients == []


def test_tray_shows_own_ip_and_this_device():
    from pangolin_gui.tray import build_menu_model
    from pangolin_gui.menu_model import walk

    acc = Account(user_id="u1", host="https://p.example", email="a@example.com", org_id="o1")
    me = OrgClient(0, "my-pc", "100.90.128.2", True, is_self=True)
    state = AppState(conn=ConnState.CONNECTED, accounts=[acc], active_account=acc, own_ip="100.90.128.2",
                     status=OlmStatus(connected=True, registered=True, org_id="o1"),
                     clients=[me], clients_error="forbidden")
    calls = []

    class Ctl:
        def __getattr__(self, name):
            return lambda *a: calls.append((name, a))

    nodes = build_menu_model(state, Ctl())
    by_id = {n.id: n for n in walk(nodes)}
    top = [n.id for n in nodes]
    assert top.index("own_ip") == top.index("status") + 1
    assert by_id["own_ip"].label == "This device: 100.90.128.2"
    by_id["own_ip"].action()
    assert calls[-1] == ("copy_client_ip", ("100.90.128.2", "this device"))
    assert by_id["client:self"].label == "my-pc (this device)  ·  100.90.128.2"
    by_id["client:self"].action()
    assert calls[-1] == ("copy_client_ip", ("100.90.128.2", "my-pc"))
    assert by_id["clients"].label == "Online Clients"          # count excludes this device
    assert by_id["clients:empty"].label == "Your role may not list clients"


def test_no_own_ip_entry_when_disconnected():
    from pangolin_gui.tray import build_menu_model
    from pangolin_gui.menu_model import walk

    acc = Account(user_id="u1", host="https://p.example", email="a@example.com")
    nodes = build_menu_model(AppState(conn=ConnState.DISCONNECTED, accounts=[acc], active_account=acc,
                                      own_ip="100.90.128.2"), Recorder())
    assert "own_ip" not in [n.id for n in walk(nodes)]


class Recorder:
    def __getattr__(self, name):
        return lambda *a: None
