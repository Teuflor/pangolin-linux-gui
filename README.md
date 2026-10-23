# Pangolin GUI for Linux

Unofficial tray client for [Pangolin](https://pangolin.net) on Linux, modelled on the
official Windows client. It is a GUI layer on top of the official
[Pangolin CLI](https://github.com/fosrl/cli), which does the actual work.

Features (as in the Windows client):

- Tray icon (orange = connected, gray = disconnected) with Connect/Disconnect
- Sites submenu: status, Direct/Relay/Local, endpoint, last seen, RTT per site
- Switch accounts and organizations, add an account (device-code login in the browser), log out
- Status window, log viewer, preferences (DNS options, autostart, connect on start)

Not yet included: exit node selection (the CLI has no non-interactive way to list exit nodes).

## Requirements

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1
```

Also the Pangolin CLI (`pangolin` in `PATH`):
see https://docs.pangolin.net/manage/clients/install-client

GNOME shows tray icons only with the *AppIndicator and KStatusNotifierItem Support*
extension. KDE, XFCE, Cinnamon and MATE support them out of the box. Without a tray
the app opens its status window instead.

## Run

```bash
./bin/pangolin-gui            # opens the status window, icon in the tray
./bin/pangolin-gui --hidden   # tray only (used for autostart)
```

## How it works

| Task | Implementation |
|---|---|
| Status | HTTP over `/var/run/olm.sock` (`GET /status`), polled every 2 s |
| Connect | `pangolin up client --silent`. The CLI starts the daemon via `sudo`; with no terminal, sudo asks through `bin/pangolin-gui-askpass` (GTK password dialog) |
| Disconnect | `pangolin down client` |
| Accounts | `~/.config/pangolin/accounts.json` (read only) |
| Organizations | REST API `GET /api/v1/user/{id}/orgs` with the CLI session |
| Login | `pangolin auth login <host>` in a pseudo terminal; the code is shown in the dialog |

See `ARCHITECTURE.md` for details.

## Tests

```bash
python3 -m pytest
```
