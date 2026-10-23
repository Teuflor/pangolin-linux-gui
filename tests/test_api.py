import json
import urllib.error
from io import BytesIO

import pytest

from pangolin_gui import api as api_mod
from pangolin_gui.api import ApiError, PangolinApi, build_base_url
from pangolin_gui.models import Account


class FakeResponse:
    def __init__(self, status: int, payload):
        self.status = status
        self._data = json.dumps(payload).encode()

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.fixture
def account():
    return Account(user_id="user/123", host="https://app.pangolin.net",
                   email="test@example.com", session_token="secrettoken")


def fake_urlopen(monkeypatch, response=None, error=None, seen=None):
    def _open(req, timeout=None, context=None):
        if seen is not None:
            seen.append(req)
        if error is not None:
            raise error
        return response
    monkeypatch.setattr(api_mod.urllib.request, "urlopen", _open)


@pytest.mark.parametrize("host", ["https://h.example", "https://h.example/", "https://h.example/api/v1"])
def test_base_url(host):
    assert build_base_url(host) == "https://h.example/api/v1"


def test_list_orgs_sorted_and_request_shape(monkeypatch, account):
    seen = []
    payload = {"success": True, "data": {"orgs": [
        {"orgId": "b", "name": "zoo"}, {"orgId": "a", "name": "Alpha"}, {"orgId": "c", "name": "beta"}]}}
    fake_urlopen(monkeypatch, FakeResponse(200, payload), seen=seen)
    orgs = PangolinApi(account).list_orgs()
    assert [o.org_id for o in orgs] == ["a", "c", "b"]
    req = seen[0]
    assert req.full_url == "https://app.pangolin.net/api/v1/user/user%2F123/orgs"
    assert req.get_header("Cookie") == "p_session_token=secrettoken"
    assert req.get_header("X-csrf-token") == "x-csrf-protection"


def test_success_false_raises(monkeypatch, account):
    fake_urlopen(monkeypatch, FakeResponse(200, {"success": False, "message": "boom"}))
    with pytest.raises(ApiError) as exc:
        PangolinApi(account).list_orgs()
    assert str(exc.value) == "boom"
    assert exc.value.auth_expired is False


@pytest.mark.parametrize("code,expired,forbidden", [(401, True, False), (403, False, True)])
def test_auth_expired(monkeypatch, account, code, expired, forbidden):
    err = urllib.error.HTTPError("https://x", code, "nope", {},
                                 BytesIO(json.dumps({"success": False, "message": "Unauthorized"}).encode()))
    fake_urlopen(monkeypatch, error=err)
    with pytest.raises(ApiError) as exc:
        PangolinApi(account).list_orgs()
    assert exc.value.auth_expired is expired
    assert exc.value.forbidden is forbidden
    assert "secrettoken" not in str(exc.value)


def test_network_error(monkeypatch, account):
    fake_urlopen(monkeypatch, error=urllib.error.URLError("dns"))
    with pytest.raises(ApiError) as exc:
        PangolinApi(account).list_orgs()
    assert "secrettoken" not in str(exc.value)
