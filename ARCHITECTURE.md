# Pangolin Linux GUI – Architektur

Ziel: Tray-App für Linux, angelehnt an den offiziellen Windows-Client (fosrl/windows),
die auf der offiziellen Pangolin-CLI (`pangolin`, fosrl/cli) aufsetzt.
Referenz-Quellcode: `~/pangolin-ref/cli` und `~/pangolin-ref/windows`.

Stack: Python 3.12, PyGObject, **GTK 3** (`gi.require_version("Gtk", "3.0")`),
Tray via **AyatanaAppIndicator3** (`gi.require_version("AyatanaAppIndicator3", "0.1")`).
Keine weiteren Python-Abhängigkeiten außer der Standardbibliothek. Tests mit pytest.

## Fakten über die CLI (verifiziert im Quellcode)

- Config-Verzeichnis: `~/.config/pangolin/` mit `config.json` und `accounts.json`.
- `accounts.json`: `{"activeUserId": "...", "accounts": {"<userId>": {"userId","host","email",
  "username"?, "name"?, "sessionToken", "orgId"?, "olmCredentials"?: {"id","secret"},
  "serverInfo"?: {"version","build",...}}}}`
- Tunnel-Daemon (olm) läuft als root, HTTP über Unix-Socket `/var/run/olm.sock`:
  - `GET /status` → JSON: `connected, registered, terminated, version, agent, orgId,
    peers: {"<siteId>": {siteId, name, connected, rtt (ns, int), lastSeen (ISO), endpoint,
    isRelay, isLocal, peerAddress}}, exitNode?: {connected, rtt, lastSeen, endpoint},
    gatewayActive, error?: {code, message}`
  - `POST /exit` → `{"status": "..."}`
  - `POST /switch-org` Body `{"org_id": "..."}`
  - Socket fehlt ⇒ Client läuft nicht.
- REST-API: Basis `<host>/api/v1`, Antwort-Hülle `{"data":..., "success":bool, "error":..., "message":...}`.
  Auth: Cookie `p_session_token=<sessionToken>` und Header `X-CSRF-Token: x-csrf-protection`.
  `GET /user/{userId}/orgs` → `data.orgs: [{orgId, name}]`.
- CLI-Kommandos: `pangolin up client --silent [--org ID]`, `pangolin down client`,
  `pangolin status client --json`, `pangolin auth login <host>`, `pangolin auth logout`,
  `pangolin select org --org ID`, `pangolin select account --account EMAIL --host HOST`,
  `pangolin select exit-node --exit-node NICE-ID`, `pangolin logs client [-f] [-n N]`,
  `pangolin version`, `pangolin config get|set <key> [value]`.
- `pangolin up client` (detached) ruft intern `sudo sh -c ...` auf. Ohne Terminal nutzt sudo
  `SUDO_ASKPASS`. Die GUI startet `up` daher **ohne Controlling-TTY** (`start_new_session=True`,
  stdin=DEVNULL) mit `SUDO_ASKPASS=<repo>/bin/pangolin-gui-askpass`.
  Der root-Kindprozess ist `PANGOLIN_SUBPROCESS=1 pangolin up client --org … --id … --secret …
  --endpoint … [Flags]`; er findet das Config-/Log-Verzeichnis des Benutzers über `SUDO_USER`.
  `--org/--id/--secret/--endpoint` lassen sich auch als `PANGOLIN_ORG`, `PANGOLIN_CLIENT_ID`,
  `PANGOLIN_CLIENT_SECRET`, `PANGOLIN_ENDPOINT` setzen. Achtung: `up.override_dns=false` gibt
  die CLI dabei nicht weiter (nur gesetzte `true`-Werte).
- Systemdienst-Modus (`install.sh --system-service`, `pangolin_gui/service.py`): Ist
  `pangolin-gui@.service` installiert, startet/stoppt `cli.up()`/`cli.down()` den Dienst per
  `systemctl --no-ask-password`; Polkit erlaubt das dem Benutzer für seine eigene Instanz. Das
  Startprogramm `system/pangolin-gui-client` (root, eigenständig, importiert nichts aus dem Repo)
  baut den Aufruf oben aus `accounts.json`/`config.json` nach, mit allen `up.*`-Werten explizit
  und dem Secret in `PANGOLIN_CLIENT_SECRET`. Lehnt Polkit ab, fällt `up()` auf sudo zurück.
- `pangolin auth login <host>` gibt eine Zeile `First copy your one-time code: XXXX-XXXX` aus und
  pollt dann selbst bis zu 5 Minuten. Login-URL: `<host>/auth/login/device?code=<code>`.
  Ist schon ein Konto aktiv, fragt die CLI interaktiv (huh-TUI) „Log in again / different account“
  → darum Login in einem **Pseudo-Terminal** (`pty`) ausführen.

## Module und Zuständigkeiten

| Datei | Inhalt | Wer |
|---|---|---|
| `pangolin_gui/models.py` | Datenklassen (Vertrag, nicht ändern) | Claude |
| `pangolin_gui/olm_socket.py` | HTTP-über-Unix-Socket-Client | Strata |
| `pangolin_gui/accounts.py` | accounts.json/config.json lesen | Strata |
| `pangolin_gui/api.py` | REST-API (Orgs) | Open WebUI |
| `pangolin_gui/cli.py` | Wrapper um `pangolin`-Binary inkl. pty-Login | Antigravity |
| `pangolin_gui/tray.py` | AppIndicator-Menü wie Windows `ui/menu.go` | Antigravity |
| `pangolin_gui/windows/status_window.py` | Status-Fenster mit Peers | Open WebUI |
| `pangolin_gui/windows/logs_window.py` | Log-Fenster | Open WebUI |
| `pangolin_gui/windows/preferences.py` | Einstellungen | Open WebUI |
| `pangolin_gui/windows/login_dialog.py` | Login-Dialog (Device-Code) | Antigravity |
| `pangolin_gui/state.py`, `app.py`, `__main__.py`, `askpass.py` | Integration, Polling, Askpass | Claude |

### Schnittstellen (Signaturen sind verbindlich)

```python
# olm_socket.py
SOCKET_PATH = "/var/run/olm.sock"
class OlmError(Exception): ...
class OlmClient:
    def __init__(self, socket_path: str = SOCKET_PATH, timeout: float = 3.0): ...
    def is_running(self) -> bool                    # Socket existiert und GET /status klappt
    def get_status(self) -> OlmStatus               # wirft OlmError
    def exit(self) -> None                          # POST /exit
    def switch_org(self, org_id: str) -> None       # POST /switch-org
def parse_status(data: dict) -> OlmStatus           # reine Funktion, testbar

# accounts.py
def config_dir() -> pathlib.Path                    # ~/.config/pangolin (HOME respektieren)
def load_accounts(path: Path | None = None) -> tuple[list[Account], Account | None]
def load_config(path: Path | None = None) -> dict   # {} wenn Datei fehlt

# api.py
class ApiError(Exception): ...
class PangolinApi:
    def __init__(self, account: Account, timeout: float = 10.0): ...
    def list_orgs(self) -> list[Org]

# cli.py
class CliError(Exception): ...
def find_cli() -> str | None                        # shutil.which("pangolin") oder ~/.local/bin/pangolin, /usr/local/bin/pangolin
def version() -> str
def up(org_id: str | None = None, askpass: str | None = None) -> None   # blockiert bis sudo/Start fertig
def down() -> None
def select_org(org_id: str) -> None
def select_account(email: str, host: str) -> None
def logout() -> None
def config_set(key: str, value: str) -> None
def read_logs(lines: int = 500) -> str
class LoginSession:                                 # pty-basiert, läuft im Thread
    def __init__(self, host: str, on_code: Callable[[str, str], None],
                 on_done: Callable[[bool, str], None]): ...   # on_code(code, url); on_done(ok, msg)
    def start(self) -> None
    def cancel(self) -> None
```

UI-Module bekommen ein `controller`-Objekt (Duck-Typing) mit diesen Methoden:
`connect()`, `disconnect()`, `select_org(org_id)`, `select_account(user_id)`, `add_account()`,
`logout()`, `open_status()`, `open_logs()`, `open_preferences()`, `quit()`,
`open_url(url)`, `get_state() -> AppState`. Callbacks der Controller-Methoden blockieren nie
(Arbeit läuft in Threads, UI-Updates via `GLib.idle_add`).
UI-Fenster bieten `update(state: AppState)` und werden vom Controller bei Änderungen aufgerufen.

## Regeln für alle Beiträge
- Nur die eigene Datei anlegen/ändern. `models.py` nicht ändern.
- Keine Secrets loggen (sessionToken, olm secret).
- Keine `shell=True`-Aufrufe; Argumente als Liste.
- Code und Kommentare auf Englisch, UI-Texte auf Englisch (wie Windows-Client).

## Ergänzungen

| Datei | Inhalt |
|---|---|
| `pangolin_gui/i18n.py` | `_()`/`N_()`, Sprachdateien `locales/<code>.json`, Englisch ist Quellsprache |
| `pangolin_gui/locales/de.json` | Deutsch (Entwurf: Open WebUI, geprüft von Claude) |
| `tools/i18n_check.py` | sammelt `_()`/`N_()`-Literale per AST, prüft Vollständigkeit und Platzhalter |
| `pangolin_gui/clipboard.py` | Zwischenablage: `wl-copy` → `xclip`/`xsel` → GTK |
| `pangolin_gui/netinfo.py` | IPv4 der Schnittstelle `pangolin` (ioctl), um das eigene Gerät auszublenden |

- Texte nie bei Import übersetzen: Konstanten mit `N_()` markieren, `_()` beim Aufbau aufrufen.
- `_` nie als Wegwerfvariable verwenden (überdeckt die Übersetzungsfunktion).
- Sprachwechsel: `app.apply_language()` baut Tray neu und erzeugt offene Fenster neu.
- Online-Clients: `PangolinApi.list_online_clients()` fragt `/org/{orgId}/clients` und
  `/org/{orgId}/user-devices` mit `online=true` ab (Recht *listClients*). `StateManager` pollt
  nur bei bestehender Verbindung, höchstens alle 30 s.

## Tray (nach Praxistest 1)

| Datei | Inhalt |
|---|---|
| `pangolin_gui/menu_model.py` | `MenuNode` – Menü ohne GTK; `signature()` für Neuaufbau nur bei Änderung |
| `pangolin_gui/tray.py` | `build_menu_model(state, controller)` (testbar ohne GTK), `choose_backend()`, `TrayIcon` |
| `pangolin_gui/sni.py` | StatusNotifierItem + `com.canonical.dbusmenu` über Gio (Entwurf: Antigravity, geprüft) |
| `pangolin_gui/tray_gtk.py` | Fallback AppIndicator / Gtk.StatusIcon |

- Backend: SNI, wenn `org.kde.StatusNotifierWatcher` läuft, sonst GTK; `PANGOLIN_TRAY=sni|gtk` erzwingt.
- SNI: Activate = Statusfenster, SecondaryActivate = Verbinden/Trennen, Menü per dbusmenu.
  Anmeldung beim Watcher erst nach `NameAcquired` und erneut, wenn der Watcher neu startet.
- Nach jedem Klick baut `TrayIcon` das Menü aus dem echten Zustand neu (kein hängender Haken).
- Kein Menüeintrag als Checkbox für Verbinden/Trennen.
