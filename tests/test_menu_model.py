"""Tray menu content (TODO points 2 and 3) and backend choice – no GTK needed."""
import pytest

from pangolin_gui.menu_model import LABEL, NORMAL, RADIO, SEPARATOR, MenuNode, signature, walk
from pangolin_gui.models import Account, AppState, ConnState, OlmStatus, Org, OrgClient, Peer
from pangolin_gui.tray import build_menu_model, choose_backend


class Recorder:
    """Stands in for the controller; records which method a click calls."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *args: self.calls.append((name, args))


ACC = Account(user_id="u1", host="https://p.example", email="a@example.com", org_id="o1")


def find(nodes, node_id) -> MenuNode:
    return next(n for n in walk(nodes) if n.id == node_id)


def top_ids(nodes):
    return [n.id for n in nodes if n.kind != SEPARATOR]


def test_no_account_offers_login_and_status():
    nodes = build_menu_model(AppState(), Recorder())
    assert top_ids(nodes)[:2] == ["login", "open_status"]
    assert "toggle" not in top_ids(nodes)


@pytest.mark.parametrize("conn,label,enabled,method", [
    (ConnState.DISCONNECTED, "Connect", True, "connect"),
    (ConnState.ERROR, "Connect", True, "connect"),
    (ConnState.CONNECTED, "Disconnect", True, "disconnect"),
    (ConnState.CONNECTING, "Disconnect", True, "disconnect"),
    (ConnState.DISCONNECTING, "Disconnect", False, "disconnect"),
])
def test_connect_entry_is_plain_item_matching_state(conn, label, enabled, method):
    ctl = Recorder()
    nodes = build_menu_model(AppState(conn=conn, accounts=[ACC], active_account=ACC), ctl)
    toggle = find(nodes, "toggle")
    assert toggle.kind == NORMAL and not toggle.checked  # no checkbox that can get out of sync
    assert (toggle.label, toggle.enabled) == (label, enabled)
    toggle.action()
    assert ctl.calls[-1][0] == method


@pytest.mark.parametrize("conn", list(ConnState))
def test_open_status_always_top_level(conn):
    ctl = Recorder()
    nodes = build_menu_model(AppState(conn=conn, accounts=[ACC], active_account=ACC), ctl)
    assert "open_status" in top_ids(nodes)
    find(nodes, "open_status").action()
    assert ctl.calls == [("open_status", ())]


def test_connected_menu_has_sites_clients_and_radio_marks():
    state = AppState(
        conn=ConnState.CONNECTED, accounts=[ACC], active_account=ACC,
        orgs=[Org("o1", "One"), Org("o2", "Two")],
        status=OlmStatus(connected=True, registered=True, org_id="o2",
                         peers=[Peer(7, "Home", True, 12.0, None)]),
        clients=[OrgClient(3, "laptop", "100.90.128.7", True)])
    ctl = Recorder()
    nodes = build_menu_model(state, ctl)
    assert find(nodes, "status").kind == LABEL
    assert find(nodes, "site:7").label == "Home"
    assert all(child.kind == LABEL for child in find(nodes, "site:7").children)
    orgs = find(nodes, "org").children
    assert [(n.kind, n.checked) for n in orgs] == [(RADIO, False), (RADIO, True)]  # live org wins
    find(nodes, "client:3").action()
    assert ctl.calls[-1] == ("copy_client_ip", ("100.90.128.7", "laptop"))


def test_sites_hidden_when_disconnected():
    nodes = build_menu_model(AppState(conn=ConnState.DISCONNECTED, accounts=[ACC], active_account=ACC),
                             Recorder())
    ids = [n.id for n in walk(nodes)]
    assert "sites" not in ids and "clients" not in ids


def test_signature_ignores_callbacks_but_sees_labels():
    a = [MenuNode("x", "A", action=lambda: None)]
    b = [MenuNode("x", "A", action=lambda: 1)]
    c = [MenuNode("x", "B")]
    assert signature(a) == signature(b) != signature(c)


@pytest.mark.parametrize("value,expected", [("sni", "sni"), ("GTK", "gtk")])
def test_backend_can_be_forced(value, expected):
    assert choose_backend({"PANGOLIN_TRAY": value}) == expected
