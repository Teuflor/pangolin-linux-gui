"""The root-run start helper system/pangolin-gui-client (loaded from its file, no .py)."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def load_helper():
    path = ROOT / "system" / "pangolin-gui-client"
    loader = importlib.machinery.SourceFileLoader("pangolin_gui_client", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


helper = load_helper()

ACCOUNTS = {
    "activeuserid": "u1",
    "accounts": {"u1": {
        "userId": "u1", "host": "https://pangolin.example.com", "orgId": "my-org",
        "olmCredentials": {"id": "abc123", "secret": "s3cr3t"},
    }},
}


def test_build_command_from_active_account():
    argv, secret = helper.build_command(ACCOUNTS, {})
    assert argv == [helper.PANGOLIN, "up", "client", "--id=abc123",
                    "--endpoint=https://pangolin.example.com", "--org=my-org"]
    assert secret == "s3cr3t"
    assert "s3cr3t" not in " ".join(argv)


def test_settings_are_passed_explicitly():
    config = {"log_level": "debug", "up": {
        "override_dns": False, "prefer_local_routes": True,
        "upstream_dns": ["1.1.1.1:53", "9.9.9.9"], "match_domains_dns": ["*.corp.internal"],
    }}
    argv, _ = helper.build_command(ACCOUNTS, config)
    assert "--override-dns=false" in argv
    assert "--prefer-local-routes=true" in argv
    assert "--upstream-dns=1.1.1.1:53,9.9.9.9" in argv
    assert "--match-domains=*.corp.internal" in argv
    assert argv[-1] == "--log-level=debug"


def test_camel_case_active_id_is_accepted():
    accounts = dict(ACCOUNTS)
    accounts["activeUserId"] = accounts.pop("activeuserid")
    argv, _ = helper.build_command(accounts, {})
    assert "--id=abc123" in argv


@pytest.mark.parametrize("change", [
    {"host": "https://evil.example.com; rm -rf /"},
    {"host": "file:///etc/shadow"},
    {"orgId": "--attach"},
    {"olmCredentials": {"id": "x y", "secret": "s"}},
    {"olmCredentials": {"id": "ok", "secret": "with\nnewline"}},
])
def test_invalid_account_values_are_rejected(change):
    account = {**ACCOUNTS["accounts"]["u1"], **change}
    with pytest.raises(helper.ConfigError):
        helper.build_command({"activeuserid": "u1", "accounts": {"u1": account}}, {})


@pytest.mark.parametrize("up", [
    {"override_dns": "false"},
    {"upstream_dns": ["1.1.1.1 --http-addr=0.0.0.0:80"]},
    {"match_domains_dns": "not-a-list"},
])
def test_invalid_settings_are_rejected(up):
    with pytest.raises(helper.ConfigError):
        helper.build_command(ACCOUNTS, {"up": up})


def test_no_active_account():
    with pytest.raises(helper.ConfigError, match="no active"):
        helper.build_command({"accounts": {}}, {})


def test_read_user_json(tmp_path):
    path = tmp_path / "accounts.json"
    path.write_text(json.dumps(ACCOUNTS))
    assert helper.read_user_json(str(path), os.getuid()) == ACCOUNTS
    assert helper.read_user_json(str(tmp_path / "missing.json"), os.getuid()) == {}


def test_read_user_json_rejects_other_owner(tmp_path):
    path = tmp_path / "accounts.json"
    path.write_text("{}")
    with pytest.raises(helper.ConfigError, match="owned by the user"):
        helper.read_user_json(str(path), os.getuid() + 1)


def test_read_user_json_rejects_symlink(tmp_path):
    target = tmp_path / "real.json"
    target.write_text("{}")
    link = tmp_path / "accounts.json"
    link.symlink_to(target)
    with pytest.raises(helper.ConfigError):
        helper.read_user_json(str(link), os.getuid())


def test_env_carries_secret_and_user():
    import pwd
    user = pwd.getpwuid(os.getuid())
    env = helper.build_env(user, "s3cr3t")
    assert env["PANGOLIN_CLIENT_SECRET"] == "s3cr3t"
    assert env["SUDO_USER"] == user.pw_name
    assert env["PANGOLIN_SUBPROCESS"] == "1"
    assert env["HOME"] == "/root"


def test_main_refuses_without_root(capsys):
    if os.geteuid() == 0:
        pytest.skip("running as root")
    assert helper.main(["pangolin-gui-client", "nobody"]) == 2
    assert helper.main(["pangolin-gui-client", "../etc"]) == 2
