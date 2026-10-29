# Pangolin GUI for Linux

**English** · [Deutsch](README.de.md)

Unofficial tray client for [Pangolin](https://pangolin.net) on Linux, modelled on the official
[Windows client](https://github.com/fosrl/windows). The actual work is done by the official
[Pangolin CLI](https://github.com/fosrl/cli); this app is a graphical front end for it.

> **Status:** early release. Tested on an Arch-based system (CachyOS) with KDE Plasma 6 (Wayland)
> against a self-hosted Pangolin server. Other desktops and distributions are less tested;
> feedback is welcome.

## Features

- **Tray icon:** orange when connected, gray when not. **Left click** opens the status window,
  **right click** the menu, **middle click** connects or disconnects
- **Connect/Disconnect** from the menu or the status window; if you are not logged in yet, login
  starts first and the connection follows right after
- **Sites menu** like on Windows: status, connection type (Direct/Relay/Local), endpoint,
  last seen and latency per site. Sites of the organization that the tunnel does not use are
  listed too; a click explains why (clients only connect to sites with a private resource you
  may use)
- **Accounts:** switch, add (login with a one-time code in the browser), log out
- **Organizations:** switch, even while connected
- **Status window** with a table of all sites
- **Log viewer** with search, auto-refresh and highlighting
- **Online clients:** while connected, the tray menu shows which other devices of the
  organization are online. A click copies their tunnel IP to the clipboard.
- **Own IP:** shown in the tray and the status window while connected; one click copies it.
- **Preferences:** language, the CLI's DNS options, log level, autostart, connect automatically
- **Multilingual:** English and German, more languages via a JSON file
- **Connect without a password** via an optional systemd service with a polkit rule, or a
  **graphical password prompt** for the admin rights otherwise

Not included yet: choosing an exit node (the CLI can only list exit nodes interactively).

## Dependencies

The GUI is plain Python without pip packages. It only needs system packages:

| Purpose | Arch Linux | Debian / Ubuntu |
|---|---|---|
| Python 3.10+ | `python` | (preinstalled) |
| GTK bindings (PyGObject) | `python-gobject` | `python3-gi` |
| GTK 3 | `gtk3` | `gir1.2-gtk-3.0` |
| Tray icon (AppIndicator fallback) | `libayatana-appindicator` | `gir1.2-ayatanaappindicator3-0.1` |
| Admin rights when connecting | `sudo` | (preinstalled) |
| Copy IPs to the clipboard (Wayland / X11) | `wl-clipboard`, `xclip` | `wl-clipboard`, `xclip` |
| Pangolin CLI | AUR `pangolin-bin` or `get-cli.sh` | `get-cli.sh` |
| Tests (optional) | `python-pytest` | `python3-pytest` |

The package lists are also in [`deps/arch.txt`](deps/arch.txt) and
[`deps/debian.txt`](deps/debian.txt); `install.sh --deps` reads them from there.

## Installation on Arch Linux

Also applies to Manjaro, EndeavourOS, CachyOS and other Arch derivatives.

### 1. Install the Pangolin CLI

From the AUR (with an AUR helper such as `yay` or `paru`):

```bash
yay -S pangolin-bin
```

Or with the official install script
([instructions](https://docs.pangolin.net/manage/clients/install-client)):

```bash
curl -fsSL https://static.pangolin.net/get-cli.sh | bash
```

Check:

```bash
pangolin version
```

### 2. Clone the repository

```bash
git clone https://github.com/Teuflor/pangolin-linux-gui.git
cd pangolin-linux-gui
```

### 3. Dependencies and menu entry

```bash
./install.sh --deps
```

This installs the missing packages from `deps/arch.txt` with `sudo pacman -S --needed` and adds a
"Pangolin" entry to the application menu. Without `--deps` the script only shows what is missing.

By hand:

```bash
sudo pacman -S --needed python python-gobject gtk3 libayatana-appindicator sudo wl-clipboard xclip
```

### Notes for Arch

- **sudo:** on a minimal Arch install `sudo` is often not set up. Your user must be allowed to use
  `sudo` (e.g. group `wheel` and `%wheel ALL=(ALL:ALL) ALL` in `visudo`). Otherwise *Connect*
  fails, because the Pangolin CLI starts the tunnel with `sudo` (unless you install the
  system service, see below).
- **Tray icon per desktop:**
  - **KDE Plasma:** works out of the box.
  - **GNOME:** needs the extension *AppIndicator and KStatusNotifierItem Support*:
    `sudo pacman -S gnome-shell-extension-appindicator`, then log out and back in and enable the
    extension in *Extensions*.
  - **XFCE:** add the panel item *Status Tray* (*Notification Area* in older versions) to the
    panel (part of `xfce4-panel` since XFCE 4.16).
  - **Hyprland / Sway / other Wayland compositors:** need a bar with a tray, e.g. Waybar with
    the `tray` module.
  - Without a tray the app opens its status window; connecting and disconnecting work there too.
- **Notifications:** errors are shown as desktop notifications. Under window managers without a
  notification daemon, install `dunst` or `mako`.
- **Browser for login:** the default browser is opened (`xdg-open`). If nothing happens:
  `xdg-settings set default-web-browser firefox.desktop`.

## Installation on Debian / Ubuntu

1. Install the Pangolin CLI:

   ```bash
   curl -fsSL https://static.pangolin.net/get-cli.sh | bash
   ```

2. Clone the repository and install:

   ```bash
   git clone https://github.com/Teuflor/pangolin-linux-gui.git
   cd pangolin-linux-gui
   ./install.sh --deps
   ```

   This installs the packages from `deps/debian.txt` with `sudo apt-get`.

3. **GNOME (default Ubuntu):** the extension *AppIndicator and KStatusNotifierItem Support* is
   usually already active, otherwise:

   ```bash
   sudo apt install gnome-shell-extension-appindicator
   ```

## More install.sh options

```bash
./install.sh --autostart               # start in the tray at login
./install.sh --system-service          # connect without a password (see below)
./install.sh --remove-system-service   # back to the sudo password prompt
./install.sh --uninstall               # remove menu entry, icon and autostart entry
```

The repository stays where it is; the menu entry and autostart point to `bin/pangolin-gui` in
the cloned folder. After `git pull` the new version is active right away.

### Connect without a password (system service)

Only root can set up the tunnel, so without further setup the CLI asks for your password with
`sudo` every time you connect. `./install.sh --system-service` instead sets up the following
once (with `sudo`):

| File | Purpose |
|---|---|
| `/usr/local/bin/pangolin` | Pangolin CLI, owned by root (moved from `~/.local/bin`; a package in `/usr/bin` is used directly) |
| `/usr/local/lib/pangolin-gui/pangolin-gui-client` | start helper of the service (copy of `system/pangolin-gui-client`) |
| `/etc/systemd/system/pangolin-gui@.service` | systemd service `pangolin-gui@<user>.service`, not started at boot |
| `/etc/polkit-1/rules.d/50-pangolin-gui.rules` | lets the logged-in user start, stop and restart **only their own** service without a password |

After that, *Connect* starts the service with `systemctl` and *Disconnect* stops it. If the
polkit rule is missing, the GUI falls back to the sudo prompt. At shutdown systemd stops the
service cleanly, so DNS and routes are restored.

Security: the start helper runs as root and only reads the active account (`accounts.json`)
and the `up.*` settings (`config.json`) from `~/.config/pangolin/`, and only from regular files
owned by the user (no symlinks). It validates every value and runs nothing but
`pangolin up client`, without a shell. As with the CLI's own sudo path, the client secret is on
the command line (visible to local users in `ps`). A program running as your user can therefore
switch the tunnel on and off without a password and change the tunnel's target through your own
account files, but it cannot run any other command as root. A passwordless `sudoers` entry is
**not** recommended instead: the CLI runs `sudo sh -c "…"`, so such a rule would allow any
command as root.

After a GUI update that changes `system/`, run `./install.sh --system-service` again; likewise
after `pangolin update` if the CLI ends up in `~/.local/bin` again.

## Running

```bash
./bin/pangolin-gui            # icon in the tray only
./bin/pangolin-gui --show     # also open the status window
./bin/pangolin-gui --debug    # verbose logs in the terminal
```

The status window opens with a left click on the tray icon. Starting the app a second time
does not open a second instance but brings the status window to the front. Without a tray
(see the desktop notes above) the status window opens right away.

### Tray icon and clicks

The app registers its icon itself over D-Bus as a *StatusNotifierItem* (KDE Plasma, GNOME with
the AppIndicator extension, XFCE, Waybar):

| Click | Action |
|---|---|
| Left | open the status window or bring it to the front |
| Right | menu |
| Middle | connect / disconnect |

If no StatusNotifier service is running, the app uses AppIndicator. There, left and right click
both open the menu; the status window is reachable via *Open Status…* or the middle click.
You can force the backend:

```bash
PANGOLIN_TRAY=gtk ./bin/pangolin-gui   # AppIndicator instead of the own D-Bus icon
PANGOLIN_TRAY=sni ./bin/pangolin-gui   # force the own D-Bus icon
```

### Logs

The GUI logs to stderr: startup (language, CLI path, tray backend), loaded accounts and
organizations, connection changes, login. With `--debug` it also logs every CLI call with exit
code and last output, and every API call with its HTTP status. Passwords, session tokens and
login codes never end up in the log.

## Language

*Preferences… → Language* offers:

- **System default:** follows the desktop language (`LANGUAGE`/`LANG`, e.g. `de_DE.UTF-8` → German)
- **English**
- **Deutsch**

The change takes effect immediately: the tray menu and open windows are rebuilt in the new
language. The password prompt for `sudo` follows the setting too.

### Adding a language

Each language is a file `pangolin_gui/locales/<code>.json`, e.g. `fr.json`:

```json
{
  "name": "Français",
  "strings": {
    "Connect": "Se connecter",
    "Version {version}": "Version {version}"
  }
}
```

The check tool creates a template with all strings:

```bash
echo '{"name": "Français", "strings": {}}' > pangolin_gui/locales/fr.json
python3 tools/i18n_check.py --update   # adds all strings (empty) to every language file
python3 tools/i18n_check.py            # shows missing translations and placeholder errors
```

Placeholders such as `{version}` or `{ip}` must be kept in the translation. Missing entries are
shown in English. The new language appears in the preferences automatically.

## Online clients

While connected, the tray has a submenu **Online Clients (n)**. It lists the other devices of
the current organization that are online, each with name and tunnel IP
(e.g. `laptop-anna · 100.90.128.7`). For user devices the tooltip shows the owner.

- **Clicking an entry** copies the IP to the clipboard and confirms it with a notification.
- **Refresh** reloads the list right away; otherwise it is fetched every 30 seconds, and only
  while connected.
- **This device** is listed first, marked `(this device)`, so you can copy your own IP from
  here too. It is recognized by the IP of the `pangolin` interface; the count in the title
  only counts the other devices.

**Own IP:** while connected, the tray shows **This device: 100.90.x.y** right below the
status line, and the status window has an **Own IP** row with a **Copy** button. Both copy
your tunnel IP to the clipboard. The IP is read locally from the `pangolin` interface, so it
works without any API permission.

**Permission:** the list comes from the Pangolin API (`/org/{orgId}/clients` and
`/org/{orgId}/user-devices`). Both require the *listClients* permission, which admins have by
default in Pangolin. Without it, the menu shows "Your role may not list clients" – your own
device is still listed. An admin can grant the permission to your role.

**Clipboard:** a tray app has no focus when a menu item is clicked. Under Wayland many
compositors then do not accept the clipboard from GTK. The app therefore uses `wl-copy`
(package `wl-clipboard`) or `xclip` under X11 when available; `install.sh --deps` installs both.

## First-run test guide

1. Start `./bin/pangolin-gui --debug` in a terminal so errors show up there.
2. **Log in:** tray → *Log In…* (or Connect in the status window) → choose Cloud or your own
   server → copy the code → *Open browser* → confirm in the browser.
3. **Organization:** tray → *Organization* should list your organizations.
4. **Connect:** tray → *Connect*. Without the system service a password prompt for `sudo`
   appears. The status then changes via *Registering…* to *Connected* and the icon turns orange.
5. **Sites:** tray → *Sites* and *Open Status…* should show the sites with latency.
6. **Logs:** tray → *Logs…*
7. **Disconnect:** tray → *Disconnect*.

Cross-check in a terminal: `pangolin status client` should show the same as the GUI.

If something goes wrong, please keep the terminal output of `--debug` and
`pangolin logs client -n 100`.

## How it works

| Task | Implementation |
|---|---|
| Status | HTTP over the Unix socket `/var/run/olm.sock` (`GET /status`), polled every 2 s |
| Connect | With the system service: `systemctl start pangolin-gui@<user>.service` (no password, see above). Otherwise `pangolin up client --silent`: the CLI starts the tunnel with `sudo`; without a terminal, `sudo` asks via `bin/pangolin-gui-askpass` (GTK password dialog) |
| Disconnect | With the system service: `systemctl stop …`, otherwise `pangolin down client` |
| Accounts | `~/.config/pangolin/accounts.json` (read only) |
| Organizations | REST API `GET /api/v1/user/{id}/orgs` with the CLI's session |
| Login | `pangolin auth login <host>` in a pseudo terminal; the GUI shows the code |
| Preferences | `pangolin config set up.* …`, the GUI's own values in `~/.config/pangolin-gui/` |

The password from the dialog only goes to `sudo` and is neither stored nor logged. To connect
without a password, use the system service (`./install.sh --system-service`), not a `sudoers`
entry.

Architecture details (in German) are in [`ARCHITECTURE.md`](ARCHITECTURE.md).

## Project structure

```
bin/pangolin-gui            start script
bin/pangolin-gui-askpass    password dialog for sudo
pangolin_gui/
  app.py                    Gtk.Application and controller
  state.py                  polling, state for the UI
  cli.py                    calls to the Pangolin CLI, login in a pseudo terminal
  service.py                system service mode: systemctl start/stop
  olm_socket.py             client for the tunnel daemon (Unix socket)
  api.py                    REST API (organizations)
  accounts.py               read the CLI's accounts and configuration
  tray.py                   menu content (build_menu_model) and choice of tray backend
  menu_model.py             toolkit-neutral menu model
  sni.py                    tray icon over D-Bus (StatusNotifierItem + dbusmenu)
  tray_gtk.py               fallback: AppIndicator / Gtk.StatusIcon
  i18n.py                   translations (_() and N_())
  locales/de.json           German strings
  clipboard.py, netinfo.py  clipboard, own tunnel IP
  windows/                  status, logs, preferences, login
system/                     system service: start helper (runs as root), systemd unit, polkit rule
data/icons/                 tray icons (sources in data/icons/src/)
tools/i18n_check.py         collect strings, check language files
tests/                      pytest
deps/arch.txt               package list Arch
deps/debian.txt             package list Debian/Ubuntu
install.sh                  dependencies, menu entry, autostart, system service
```

## Tests

```bash
sudo pacman -S python-pytest      # Arch
sudo apt install python3-pytest   # Debian/Ubuntu
python3 -m pytest
```

The tests need neither GTK nor the Pangolin CLI nor a server.

## Troubleshooting

| Problem | Solution |
|---|---|
| `Namespace Gtk not available` | `gtk3` + `python-gobject` (Arch) or `gir1.2-gtk-3.0` (Debian) are missing |
| No tray icon, only the status window | the desktop has no tray, see the notes above |
| Tray icon missing or reacting wrongly | check the log line `tray backend: …`; try `PANGOLIN_TRAY=gtk` |
| *Connect*: "Authentication failed or was cancelled" | wrong password or the user may not use `sudo` |
| *Connect* with system service: "The tunnel service stopped right after starting" | `journalctl -u pangolin-gui@$USER` shows the reason; after a GUI update run `./install.sh --system-service` again |
| *Connect* hangs at *Registering…* | check `pangolin logs client -n 100`; is the server reachable? |
| Organizations stay empty | session expired: tray → *Account* → *Add Account…* |
| Online clients: "Your role may not list clients" | the role lacks *listClients*, see Online clients |
| IP is not copied | install `wl-clipboard` (Wayland) or `xclip` (X11) |
| Language does not change | click *Save* in the preferences; with "System default" check `echo $LANG` |
| "No permission to access /var/run/olm.sock" | the socket belongs to root; please report it with `ls -l /var/run/olm.sock` |

## License and trademarks

This project is licensed under the [GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0).

Pangolin and the Pangolin logo are trademarks of Fossorial, Inc. This project is an unofficial
client, not developed by Fossorial and not affiliated with Fossorial. It uses neither the
Pangolin logo nor code from Fossorial; the actual work is done by the separately installed
official [Pangolin CLI](https://github.com/fosrl/cli). The tray icons are original designs
(sources in `data/icons/src/`).
