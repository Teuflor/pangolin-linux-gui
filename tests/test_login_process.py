"""LoginSession against a fake `pangolin` binary (TODO point 5: no zombie processes)."""
import os
import stat
import threading
import time

import pytest

from pangolin_gui import cli


def fake_cli(tmp_path, body: str) -> str:
    path = tmp_path / "pangolin"
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def run_session(monkeypatch, tmp_path, body, cancel_after=None):
    monkeypatch.setattr(cli, "find_cli", lambda: fake_cli(tmp_path, body))
    done = threading.Event()
    result = {}

    def on_code(code, url):
        result["code"], result["url"] = code, url

    def on_done(ok, msg):
        result["ok"], result["msg"] = ok, msg
        done.set()

    session = cli.LoginSession("p.example", on_code, on_done)
    session.start()
    if cancel_after is not None:
        time.sleep(cancel_after)
        session.cancel()
    assert done.wait(15), "login session did not finish"
    session._thread.join(5)
    return session, result


def assert_reaped(session):
    proc = session._proc
    assert proc is not None and proc.returncode is not None
    with pytest.raises(ChildProcessError):
        os.waitpid(proc.pid, os.WNOHANG)  # already reaped -> no zombie left


def test_successful_login_reports_code_and_reaps(monkeypatch, tmp_path):
    session, result = run_session(monkeypatch, tmp_path,
                                  'echo "First copy your one-time code: ABCD-1234"\nsleep 0.3\nexit 0\n')
    assert result["code"] == "ABCD-1234"
    assert result["url"] == "https://p.example/auth/login/device?code=ABCD-1234"
    assert result["ok"] is True
    assert_reaped(session)


def test_cancelled_login_is_reaped(monkeypatch, tmp_path):
    session, result = run_session(monkeypatch, tmp_path,
                                  'echo "First copy your one-time code: WXYZ-0000"\nsleep 30\n',
                                  cancel_after=0.5)
    assert result["ok"] is False
    assert_reaped(session)


def test_failed_login_message(monkeypatch, tmp_path):
    session, result = run_session(monkeypatch, tmp_path, 'echo "Error: code expired"\nexit 1\n')
    assert result["ok"] is False and "code expired" in result["msg"]
    assert_reaped(session)
