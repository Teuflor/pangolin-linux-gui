"""System service mode: systemctl handling in pangolin_gui.service and its use in cli."""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest

from pangolin_gui import cli, service


def done(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def shown(active, sub):
    return done(stdout=f"ActiveState={active}\nSubState={sub}\n")


@pytest.fixture
def clock(monkeypatch):
    """Fake time: every sleep advances the clock by its argument."""
    now = [0.0]
    monkeypatch.setattr(service.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(service.time, "sleep", lambda s: now.__setitem__(0, now[0] + s))
    return now


@pytest.fixture
def systemctl(monkeypatch):
    calls = []
    replies = {}

    def fake(*args, timeout=30.0):
        calls.append(args)
        reply = replies.get(args[0], done())
        return reply(args) if callable(reply) else reply

    monkeypatch.setattr(service, "_systemctl", fake)
    fake.calls, fake.replies = calls, replies
    return fake


def test_unit_name_uses_login_user():
    assert service.unit_name("alice") == "pangolin-gui@alice.service"


def test_systemctl_never_prompts(monkeypatch):
    run = MagicMock(return_value=done())
    monkeypatch.setattr(service.subprocess, "run", run)
    service._systemctl("stop", "x.service")
    assert run.call_args[0][0] == ["systemctl", "--no-ask-password", "stop", "x.service"]


def test_state_parses_properties(systemctl):
    systemctl.replies["show"] = shown("activating", "auto-restart")
    assert service.state("u.service") == ("activating", "auto-restart")
    assert service.is_active("u.service")


def test_start_waits_until_running(systemctl, clock):
    systemctl.replies["show"] = shown("active", "running")
    service.start("u.service")
    assert systemctl.calls[0] == ("restart", "u.service")
    assert clock[0] >= 2.0


def test_start_fails_when_helper_exits(systemctl, clock):
    systemctl.replies["show"] = shown("activating", "auto-restart")
    with pytest.raises(service.ServiceError) as err:
        service.start("u.service")
    assert "journalctl -u u.service" in str(err.value)


def test_start_reports_polkit_denial(systemctl):
    systemctl.replies["restart"] = done(1, stderr="Failed to restart u.service: Interactive authentication required.")
    with pytest.raises(service.ServiceError) as err:
        service.start("u.service")
    assert err.value.denied


def test_cli_up_uses_service(monkeypatch):
    monkeypatch.setattr(service, "installed", lambda: True)
    start = MagicMock()
    monkeypatch.setattr(service, "start", start)
    run = MagicMock()
    monkeypatch.setattr(subprocess, "run", run)
    cli.up(org_id="o1", askpass="/x/askpass")
    start.assert_called_once()
    run.assert_not_called()


def test_cli_up_falls_back_to_sudo_when_denied(monkeypatch):
    monkeypatch.setattr(service, "installed", lambda: True)
    monkeypatch.setattr(service, "start", MagicMock(side_effect=service.ServiceError("no", denied=True)))
    monkeypatch.setattr(cli, "find_cli", lambda: "/usr/bin/pangolin")
    run = MagicMock(return_value=done())
    monkeypatch.setattr(subprocess, "run", run)
    cli.up(askpass="/x/askpass")
    assert run.call_args[0][0] == ["/usr/bin/pangolin", "up", "client", "--silent"]
    assert run.call_args[1]["env"]["SUDO_ASKPASS"] == "/x/askpass"


def test_cli_up_reports_service_failure(monkeypatch):
    monkeypatch.setattr(service, "installed", lambda: True)
    monkeypatch.setattr(service, "start", MagicMock(side_effect=service.ServiceError("helper failed")))
    with pytest.raises(cli.CliError, match="helper failed"):
        cli.up()


def test_cli_down_stops_active_service(monkeypatch):
    monkeypatch.setattr(service, "installed", lambda: True)
    monkeypatch.setattr(service, "is_active", lambda: True)
    stop = MagicMock()
    monkeypatch.setattr(service, "stop", stop)
    run = MagicMock()
    monkeypatch.setattr(subprocess, "run", run)
    cli.down()
    stop.assert_called_once()
    run.assert_not_called()


def test_cli_down_uses_cli_when_service_not_running(monkeypatch):
    monkeypatch.setattr(service, "installed", lambda: True)
    monkeypatch.setattr(service, "is_active", lambda: False)
    monkeypatch.setattr(cli, "find_cli", lambda: "/usr/bin/pangolin")
    run = MagicMock(return_value=done())
    monkeypatch.setattr(subprocess, "run", run)
    cli.down()
    assert run.call_args[0][0] == ["/usr/bin/pangolin", "down", "client"]
