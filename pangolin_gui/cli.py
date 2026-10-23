"""CLI wrapper around the official Pangolin CLI binary.

Implements process execution, ANSI stripping, error handling,
and pty-based interactive authentication.
"""
from __future__ import annotations

import logging
import os
import re
import select
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from pangolin_gui.i18n import _

log = logging.getLogger(__name__)

# Regex matching ANSI escape sequences (colors, cursor movement, OSC, etc.)
ANSI_ESCAPE_RE = re.compile(
    r"\x1b(?:"
    r"\[[0-?]*[ -/]*[@-~]"  # CSI sequences
    r"|\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC sequences
    r"|[@-Z\\-_]"  # 2-character escape sequences
    r")"
)

# Regex matching the one-time device auth code printed by 'pangolin auth login'
DEVICE_CODE_RE = re.compile(r"First copy your one-time code:\s*([A-Za-z0-9_-]+)")


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    if not text:
        return ""
    return ANSI_ESCAPE_RE.sub("", text)


def parse_device_code(text: str) -> str | None:
    """Extract the one-time code from Pangolin CLI output, if present."""
    match = DEVICE_CODE_RE.search(strip_ansi(text))
    return match.group(1) if match else None


def _tail(text: str, lines: int = 3) -> str:
    rows = [r.strip() for r in (text or "").splitlines() if r.strip()]
    return " | ".join(rows[-lines:])


class CliError(Exception):
    """Raised when a Pangolin CLI command fails or cannot be executed."""

    def __init__(
        self,
        message: str,
        returncode: int | None = None,
        stderr: str = "",
        stdout: str = "",
    ):
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = stdout


def find_cli() -> str | None:
    """Locate the pangolin CLI executable in PATH or standard user/system directories."""
    found = shutil.which("pangolin")
    if found:
        return found

    candidates = [
        Path.home() / ".local" / "bin" / "pangolin",
        Path("/usr/local/bin/pangolin"),
        Path("/usr/bin/pangolin"),
    ]
    for p in candidates:
        try:
            if p.is_file() and os.access(p, os.X_OK):
                return str(p)
        except OSError:
            continue

    return None


def _run_cli(
    args: list[str],
    timeout: float = 30.0,
    env: dict[str, str] | None = None,
    stdin=subprocess.DEVNULL,
    start_new_session: bool = True,  # detach from any terminal so TUIs/prompts never grab it
) -> str:
    """Execute a Pangolin CLI subcommand with argument list and return stripped stdout."""
    cli_path = find_cli()
    if not cli_path:
        raise CliError(_("pangolin CLI binary not found"))

    full_cmd = [cli_path] + args
    log.debug("run: %s", " ".join(full_cmd))
    started = time.monotonic()
    try:
        proc = subprocess.run(
            full_cmd,
            stdin=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            env=env,
            start_new_session=start_new_session,
        )
    except subprocess.TimeoutExpired as e:
        raise CliError(
            _("Command '{command}' timed out after {timeout}s").format(
                command=" ".join(full_cmd), timeout=timeout
            )
        ) from e
    except Exception as e:
        raise CliError(f"Failed to execute '{' '.join(full_cmd)}': {e}") from e

    stdout = strip_ansi(proc.stdout)
    stderr = strip_ansi(proc.stderr)
    log.debug("exit %s after %.1fs: %s", proc.returncode, time.monotonic() - started,
              _tail(stderr or stdout))

    if proc.returncode != 0:
        err_output = stderr.strip() or stdout.strip()
        lines = [line.strip() for line in err_output.splitlines() if line.strip()]
        tail = "\n".join(lines[-5:]) if lines else f"Process exited with code {proc.returncode}"
        raise CliError(tail, returncode=proc.returncode, stderr=stderr, stdout=stdout)

    return stdout


def version() -> str:
    """Return the pangolin CLI version string (first line of output)."""
    out = _run_cli(["version"], timeout=15.0)
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    if not lines:
        return ""
    return lines[0]


def up(org_id: str | None = None, askpass: str | None = None) -> None:
    """Start client connection silently.

    Blocks until sudo authorization and daemon launch complete.
    Runs with no controlling terminal and SUDO_ASKPASS if provided.
    """
    args = ["up", "client", "--silent"]
    log.info("connecting (org=%s, askpass=%s)", org_id or "default", bool(askpass))
    if org_id:
        args.extend(["--org", org_id])

    cmd_env = os.environ.copy()
    if askpass:
        cmd_env["SUDO_ASKPASS"] = askpass

    _run_cli(
        args,
        timeout=120.0,
        env=cmd_env,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )


def down() -> None:
    """Stop the running client connection."""
    _run_cli(["down", "client"], timeout=30.0)


def select_org(org_id: str) -> None:
    """Switch the selected organization in configuration and active client."""
    _run_cli(["select", "org", "--org", org_id], timeout=30.0)


def select_account(email: str, host: str) -> None:
    """Select the active account by email and server host."""
    _run_cli(["select", "account", "--account", email, "--host", host], timeout=30.0)


def logout() -> None:
    """Log out of the current Pangolin account."""
    _run_cli(["auth", "logout"], timeout=30.0)


def config_set(key: str, value: str) -> None:
    """Set a configuration key to value."""
    _run_cli(["config", "set", key, value], timeout=30.0)


def read_logs(lines: int = 500) -> str:
    """Read the last N lines of client logs via 'pangolin logs client -n N'."""
    return _run_cli(["logs", "client", "-n", str(lines)], timeout=30.0)


class LoginSession:
    """Interactive pty-based login session running in a background thread."""

    def __init__(
        self,
        host: str,
        on_code: Callable[[str, str], None],
        on_done: Callable[[bool, str], None],
    ):
        self.host = host
        self.on_code = on_code
        self.on_done = on_done

        self._thread: threading.Thread | None = None
        self._proc: subprocess.Popen | None = None
        self._master_fd: int | None = None
        self._cancelled = False
        self._code_called = False
        self._done_called = False
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start the background login thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run,
            name="PangolinLoginSessionThread",
            daemon=True,
        )
        self._thread.start()

    def cancel(self) -> None:
        """Cancel the login session and terminate the process group."""
        self._cancelled = True
        proc = self._proc
        if proc and proc.poll() is None:
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                try:
                    proc.terminate()
                except Exception:
                    pass
            except Exception:
                pass

    def _reap(self) -> int:
        """Wait for the child so it never lingers as a zombie, killing it if needed."""
        if self._proc is None:
            return -1
        try:
            return self._proc.wait(timeout=10)  # the pty may report EOF before exit
        except subprocess.TimeoutExpired:
            self.cancel()
            try:
                return self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self._proc.pid, signal.SIGKILL)
                except OSError:
                    pass
                return self._proc.wait()

    def _finish(self, ok: bool, message: str) -> None:
        with self._lock:
            if self._done_called:
                return
            self._done_called = True
        try:
            self.on_done(ok, message)
        except Exception:
            pass

    def _run(self) -> None:
        cli_path = find_cli()
        if not cli_path:
            self._finish(False, _("pangolin CLI binary not found"))
            return

        clean_host = self.host.strip()
        if clean_host:
            clean_host = clean_host.rstrip("/")
            if not clean_host.startswith(("http://", "https://")):
                clean_host = "https://" + clean_host

        cmd = [cli_path, "auth", "login"]
        log.info("login started for %s", clean_host or "(prompt)")
        if clean_host:
            cmd.append(clean_host)

        try:
            master_fd, slave_fd = os.openpty()
            self._master_fd = master_fd
        except Exception as e:
            self._finish(False, _("Failed to allocate pty: {error}").format(error=e))
            return

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                start_new_session=True,
                close_fds=True,
            )
        except Exception as e:
            try:
                os.close(slave_fd)
            except OSError:
                pass
            try:
                os.close(master_fd)
            except OSError:
                pass
            self._master_fd = None
            self._finish(False, _("Failed to start pangolin: {error}").format(error=e))
            return

        try:
            os.close(slave_fd)
        except OSError:
            pass

        output_chunks: list[str] = []
        raw_buffer = ""
        prompt_handled = False
        org_prompt_handled = False

        try:
            while not self._cancelled:
                r, _w, _x = select.select([master_fd], [], [], 0.1)
                if r:
                    try:
                        data = os.read(master_fd, 1024)
                    except OSError:
                        # EIO indicates EOF in Linux pty
                        break
                    if not data:
                        break

                    chunk = data.decode("utf-8", errors="replace")
                    output_chunks.append(chunk)
                    raw_buffer += chunk
                    stripped = strip_ansi(raw_buffer)

                    # Handle huh select prompt:
                    # "Log in again as …" (option 0) / "Log in to a different account" (option 1)
                    if not prompt_handled:
                        if (
                            "Log in to a different account" in stripped
                            or "Log in again as" in stripped
                            or "You already have an account" in stripped
                        ):
                            prompt_handled = True
                            try:
                                # Send down-arrow escape sequence then Enter
                                os.write(master_fd, b"\x1b[B")
                                time.sleep(0.05)
                                os.write(master_fd, b"\r")
                            except OSError:
                                pass

                    # If prompted to select an organization during initial setup
                    if not org_prompt_handled and "Select an organization" in stripped:
                        org_prompt_handled = True
                        try:
                            # Accept first/default option
                            os.write(master_fd, b"\r")
                        except OSError:
                            pass

                    # Parse one-time device authentication code
                    if not self._code_called:
                        code = parse_device_code(stripped)
                        if code:
                            self._code_called = True
                            device_url = f"{clean_host}/auth/login/device?code={code}"
                            try:
                                self.on_code(code, device_url)
                            except Exception:
                                pass

                # Check if process has terminated
                if self._proc.poll() is not None:
                    # Drain any remaining bytes
                    while True:
                        r, _w, _x = select.select([master_fd], [], [], 0.05)
                        if not r:
                            break
                        try:
                            data = os.read(master_fd, 1024)
                            if not data:
                                break
                            chunk = data.decode("utf-8", errors="replace")
                            output_chunks.append(chunk)
                        except OSError:
                            break
                    break
        finally:
            try:
                os.close(master_fd)
            except OSError:
                pass
            self._master_fd = None

        exit_code = self._reap()
        log.info("login process finished: exit=%s cancelled=%s", exit_code, self._cancelled)
        if self._cancelled:
            self._finish(False, _("Login cancelled"))
            return

        full_output = strip_ansi("".join(output_chunks)).strip()

        if exit_code == 0:
            self._finish(True, _("Login successful"))
        else:
            lines = [line.strip() for line in full_output.splitlines() if line.strip()]
            err_msg = lines[-1] if lines else _("Login failed (exit code {code})").format(code=exit_code)
            self._finish(False, err_msg)
