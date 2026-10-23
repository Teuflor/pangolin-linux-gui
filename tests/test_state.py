import json

import pytest

from pangolin_gui import state as state_mod
from pangolin_gui.models import ConnState, OlmStatus, Org
from pangolin_gui.olm_socket import OlmError
from pangolin_gui.state import StateManager, derive_conn

UP = OlmStatus(connected=True, registered=True, org_id="o1")
REGISTERING = OlmStatus(connected=True, registered=False)
FAILED = OlmStatus(connected=False, error_message="auth failed")


@pytest.mark.parametrize("status,transition,expected", [
    (None, None, ConnState.DISCONNECTED),
    (None, ConnState.CONNECTING, ConnState.CONNECTING),
    (REGISTERING, None, ConnState.CONNECTING),
    (UP, None, ConnState.CONNECTED),
    (UP, ConnState.CONNECTING, ConnState.CONNECTED),
    (UP, ConnState.DISCONNECTING, ConnState.DISCONNECTING),
    (None, ConnState.DISCONNECTING, ConnState.DISCONNECTED),
    (FAILED, None, ConnState.ERROR),
    (FAILED, ConnState.CONNECTING, ConnState.CONNECTING),
])
def test_derive_conn(status, transition, expected):
    assert derive_conn(status, transition) == expected


class FakeOlm:
    def __init__(self, status=None):
        self.status = status

    def is_running(self):
        return self.status is not None

    def get_status(self):
        if self.status is None:
            raise OlmError("not running")
        return self.status


@pytest.fixture
def accounts_file(tmp_path):
    path = tmp_path / "accounts.json"
    path.write_text(json.dumps({"activeUserId": "u1", "accounts": {
        "u1": {"userId": "u1", "host": "https://p.example", "email": "a@example.com",
               "sessionToken": "tok", "orgId": "o1"}}}))
    return path


@pytest.fixture
def no_cli(monkeypatch):
    monkeypatch.setattr(state_mod.cli, "find_cli", lambda: None)


def make_manager(accounts_file, olm, monkeypatch, orgs=None):
    calls = []

    class FakeApi:
        def __init__(self, account):
            assert account.session_token == "tok"

        def list_orgs(self):
            calls.append(1)
            return orgs or [Org("o1", "One")]

    monkeypatch.setattr(state_mod, "PangolinApi", FakeApi)
    seen = []
    mgr = StateManager(seen.append, olm=olm, accounts_path=accounts_file)
    return mgr, seen, calls


def test_poll_builds_state_and_notifies_once(accounts_file, monkeypatch, no_cli):
    mgr, seen, calls = make_manager(accounts_file, FakeOlm(UP), monkeypatch)
    mgr._poll_once()
    mgr._poll_once()  # nothing changed -> no second notification, no second API call
    assert len(seen) == 1 and len(calls) == 1
    s = seen[0]
    assert s.conn == ConnState.CONNECTED
    assert s.active_account.email == "a@example.com"
    assert [o.name for o in s.orgs] == ["One"]


def test_connect_transition_clears_when_up(accounts_file, monkeypatch, no_cli):
    olm = FakeOlm(None)
    mgr, seen, _ = make_manager(accounts_file, olm, monkeypatch)
    mgr.set_transition(ConnState.CONNECTING)
    mgr._poll_once()
    assert seen[-1].conn == ConnState.CONNECTING
    olm.status = UP
    mgr._poll_once()
    assert seen[-1].conn == ConnState.CONNECTED
    olm.status = None
    mgr._poll_once()
    assert seen[-1].conn == ConnState.DISCONNECTED  # transition did not stick


def test_error_clears_transition(accounts_file, monkeypatch, no_cli):
    mgr, seen, _ = make_manager(accounts_file, FakeOlm(None), monkeypatch)
    mgr.set_transition(ConnState.CONNECTING)
    mgr.set_error("Authentication failed")
    mgr._poll_once()
    assert seen[-1].conn == ConnState.DISCONNECTED
    assert seen[-1].last_error == "Authentication failed"


def test_accounts_reloaded_on_change(accounts_file, monkeypatch, no_cli):
    mgr, seen, calls = make_manager(accounts_file, FakeOlm(None), monkeypatch)
    mgr._poll_once()
    accounts_file.write_text(json.dumps({"activeUserId": "", "accounts": {}}))
    import os
    st = accounts_file.stat()
    os.utime(accounts_file, (st.st_atime, st.st_mtime + 5))
    mgr._poll_once()
    assert seen[-1].active_account is None and seen[-1].orgs == []
