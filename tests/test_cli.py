"""Unit tests for pangolin_gui.cli module (pure functions, parsing, subprocess mocking)."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pangolin_gui.cli import (
    CliError,
    LoginSession,
    config_set,
    down,
    find_cli,
    logout,
    parse_device_code,
    read_logs,
    select_account,
    select_org,
    strip_ansi,
    up,
    version,
)


# ============================================================================
# ANSI Stripping Tests
# ============================================================================


def test_strip_ansi_plain_text():
    assert strip_ansi("Plain text with no escapes") == "Plain text with no escapes"
    assert strip_ansi("") == ""


def test_strip_ansi_colors():
    red_text = "\x1b[31mRed text\x1b[0m"
    assert strip_ansi(red_text) == "Red text"

    rgb_text = "\x1b[38;2;255;100;0mCustom RGB\x1b[0m"
    assert strip_ansi(rgb_text) == "Custom RGB"

    bold_green = "\x1b[1;32mBold Green\x1b[0m"
    assert strip_ansi(bold_green) == "Bold Green"


def test_strip_ansi_cursor_and_screen_controls():
    cursor_ctrl = "\x1b[2K\rStarting client...\x1b[?25h"
    assert strip_ansi(cursor_ctrl) == "\rStarting client..."

    screen_clear = "\x1b[2J\x1b[HWelcome"
    assert strip_ansi(screen_clear) == "Welcome"


def test_strip_ansi_osc_and_multiline():
    osc = "\x1b]0;Pangolin Terminal\x07Hello\x1b]0;\x07 World"
    assert strip_ansi(osc) == "Hello World"

    multiline = "\x1b[1mLine 1\x1b[0m\n\x1b[34mLine 2\x1b[0m\nLine 3"
    assert strip_ansi(multiline) == "Line 1\nLine 2\nLine 3"


# ============================================================================
# One-Time Device Code Parsing Tests
# ============================================================================


def test_parse_device_code_clean():
    output = "First copy your one-time code: ABCD-1234"
    assert parse_device_code(output) == "ABCD-1234"


def test_parse_device_code_with_ansi_and_surrounding_text():
    output = (
        "\x1b[32mStarting web login...\x1b[0m\n"
        "\x1b[1mFirst copy your one-time code:\x1b[0m \x1b[36mWDJB-MJHT\x1b[0m\n"
        "Press Enter to open https://app.pangolin.net/auth/login/device in your browser...\n"
    )
    assert parse_device_code(output) == "WDJB-MJHT"


def test_parse_device_code_various_formats():
    assert parse_device_code("First copy your one-time code: 8X9Y-2Z3W") == "8X9Y-2Z3W"
    assert parse_device_code("First copy your one-time code: ABCDEFGH") == "ABCDEFGH"
    assert parse_device_code("First copy your one-time code: code_123-abc") == "code_123-abc"


def test_parse_device_code_not_present():
    assert parse_device_code("Logging in to https://app.pangolin.net...") is None
    assert parse_device_code("") is None


# ============================================================================
# find_cli Tests
# ============================================================================


def test_find_cli_via_shutil_which(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/pangolin" if cmd == "pangolin" else None)
    assert find_cli() == "/usr/bin/pangolin"


def test_find_cli_via_local_bin(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _cmd: None)

    local_bin = Path.home() / ".local" / "bin" / "pangolin"

    def mock_is_file(self):
        return self == local_bin

    def mock_access(path, mode):
        return str(path) == str(local_bin) and mode == os.X_OK

    monkeypatch.setattr(Path, "is_file", mock_is_file)
    monkeypatch.setattr(os, "access", mock_access)

    assert find_cli() == str(local_bin)


def test_find_cli_via_usr_local_bin(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _cmd: None)

    usr_local = Path("/usr/local/bin/pangolin")

    def mock_is_file(self):
        return self == usr_local

    def mock_access(path, mode):
        return str(path) == str(usr_local) and mode == os.X_OK

    monkeypatch.setattr(Path, "is_file", mock_is_file)
    monkeypatch.setattr(os, "access", mock_access)

    assert find_cli() == str(usr_local)


def test_find_cli_not_found(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _cmd: None)
    monkeypatch.setattr(Path, "is_file", lambda _self: False)
    assert find_cli() is None


# ============================================================================
# CLI Command Execution and Subprocess Mocking Tests
# ============================================================================


@pytest.fixture
def mock_cli_path(monkeypatch):
    cli_fake = "/custom/bin/pangolin"
    monkeypatch.setattr("pangolin_gui.cli.find_cli", lambda: cli_fake)
    return cli_fake


def test_cli_not_found_raises_cli_error(monkeypatch):
    monkeypatch.setattr("pangolin_gui.cli.find_cli", lambda: None)
    with pytest.raises(CliError, match="pangolin CLI binary not found"):
        up()


def test_up_basic(mock_cli_path, monkeypatch):
    mock_run = MagicMock()
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="", stderr=""
    )
    monkeypatch.setattr(subprocess, "run", mock_run)

    up()

    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    assert args[0] == [mock_cli_path, "up", "client", "--silent"]
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert kwargs["start_new_session"] is True
    assert kwargs["timeout"] == 120.0
    assert "SUDO_ASKPASS" not in kwargs["env"] or kwargs["env"]["SUDO_ASKPASS"] == os.environ.get("SUDO_ASKPASS")


def test_up_with_org_id(mock_cli_path, monkeypatch):
    mock_run = MagicMock()
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="", stderr=""
    )
    monkeypatch.setattr(subprocess, "run", mock_run)

    up(org_id="org-prod-42")

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd == [mock_cli_path, "up", "client", "--silent", "--org", "org-prod-42"]


def test_up_with_askpass(mock_cli_path, monkeypatch):
    mock_run = MagicMock()
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="", stderr=""
    )
    monkeypatch.setattr(subprocess, "run", mock_run)

    askpass_path = "/usr/lib/pangolin-gui/askpass"
    up(askpass=askpass_path)

    mock_run.assert_called_once()
    kwargs = mock_run.call_args[1]
    assert kwargs["env"]["SUDO_ASKPASS"] == askpass_path


def test_up_with_org_and_askpass(mock_cli_path, monkeypatch):
    mock_run = MagicMock()
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="", stderr=""
    )
    monkeypatch.setattr(subprocess, "run", mock_run)

    up(org_id="my-org", askpass="/bin/gui-askpass")

    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    assert args[0] == [mock_cli_path, "up", "client", "--silent", "--org", "my-org"]
    assert kwargs["env"]["SUDO_ASKPASS"] == "/bin/gui-askpass"


def test_up_failure_raises_cli_error(mock_cli_path, monkeypatch):
    mock_run = MagicMock()
    mock_run.return_value = subprocess.CompletedProcess(
        args=[],
        returncode=1,
        stdout="",
        stderr="\x1b[31mError: sudo authentication failed\x1b[0m",
    )
    monkeypatch.setattr(subprocess, "run", mock_run)

    with pytest.raises(CliError) as exc_info:
        up()

    assert "sudo authentication failed" in str(exc_info.value)
    assert exc_info.value.returncode == 1


def test_down(mock_cli_path, monkeypatch):
    mock_run = MagicMock()
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="Client interface stopped", stderr=""
    )
    monkeypatch.setattr(subprocess, "run", mock_run)

    down()

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd == [mock_cli_path, "down", "client"]


def test_version_parses_first_line(mock_cli_path, monkeypatch):
    mock_run = MagicMock()
    mock_run.return_value = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="v0.4.2\n\nA new version is available: v0.5.0\nRun 'pangolin update' to update\n",
        stderr="",
    )
    monkeypatch.setattr(subprocess, "run", mock_run)

    ver = version()
    assert ver == "v0.4.2"
    mock_run.assert_called_once()
    assert mock_run.call_args[0][0] == [mock_cli_path, "version"]


def test_select_org(mock_cli_path, monkeypatch):
    mock_run = MagicMock()
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="Successfully selected organization", stderr=""
    )
    monkeypatch.setattr(subprocess, "run", mock_run)

    select_org("org-finance-01")

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd == [mock_cli_path, "select", "org", "--org", "org-finance-01"]


def test_select_account(mock_cli_path, monkeypatch):
    mock_run = MagicMock()
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="Successfully selected account", stderr=""
    )
    monkeypatch.setattr(subprocess, "run", mock_run)

    select_account("alice@corp.com", "https://pangolin.corp.internal")

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd == [
        mock_cli_path,
        "select",
        "account",
        "--account",
        "alice@corp.com",
        "--host",
        "https://pangolin.corp.internal",
    ]


def test_logout(mock_cli_path, monkeypatch):
    mock_run = MagicMock()
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="Logged out of Pangolin account", stderr=""
    )
    monkeypatch.setattr(subprocess, "run", mock_run)

    logout()

    mock_run.assert_called_once()
    assert mock_run.call_args[0][0] == [mock_cli_path, "auth", "logout"]


def test_config_set(mock_cli_path, monkeypatch):
    mock_run = MagicMock()
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="Config updated", stderr=""
    )
    monkeypatch.setattr(subprocess, "run", mock_run)

    config_set("log_level", "debug")

    mock_run.assert_called_once()
    assert mock_run.call_args[0][0] == [mock_cli_path, "config", "set", "log_level", "debug"]


def test_read_logs_defaults_and_custom_lines(mock_cli_path, monkeypatch):
    mock_run = MagicMock()
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="2026-10-23 [INFO] connected", stderr=""
    )
    monkeypatch.setattr(subprocess, "run", mock_run)

    # Default lines = 500
    logs_default = read_logs()
    assert logs_default == "2026-10-23 [INFO] connected"
    assert mock_run.call_args[0][0] == [mock_cli_path, "logs", "client", "-n", "500"]

    # Custom lines = 120
    read_logs(120)
    assert mock_run.call_args[0][0] == [mock_cli_path, "logs", "client", "-n", "120"]


def test_cli_error_multi_line_tail(mock_cli_path, monkeypatch):
    mock_run = MagicMock()
    long_stderr = "\n".join([f"Line {i}" for i in range(20)])
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=2, stdout="", stderr=long_stderr
    )
    monkeypatch.setattr(subprocess, "run", mock_run)

    with pytest.raises(CliError) as exc_info:
        down()

    err_text = str(exc_info.value)
    assert "Line 19" in err_text
    assert "Line 15" in err_text
    assert "Line 0" not in err_text  # Tail takes last 5 lines


# ============================================================================
# LoginSession Pure Logic Tests
# ============================================================================


def test_login_session_init():
    on_code = MagicMock()
    on_done = MagicMock()
    session = LoginSession("https://app.pangolin.net", on_code, on_done)

    assert session.host == "https://app.pangolin.net"
    assert session._proc is None
    assert session._cancelled is False


def test_login_session_cancel_kills_process_group():
    on_code = MagicMock()
    on_done = MagicMock()
    session = LoginSession("https://app.pangolin.net", on_code, on_done)

    mock_proc = MagicMock()
    mock_proc.pid = 9876
    mock_proc.poll.return_value = None
    session._proc = mock_proc

    with patch("os.getpgid", return_value=9876) as mock_getpgid, patch("os.killpg") as mock_killpg:
        session.cancel()
        assert session._cancelled is True
        mock_getpgid.assert_called_once_with(9876)
        mock_killpg.assert_called_once_with(9876, 15)  # signal.SIGTERM
