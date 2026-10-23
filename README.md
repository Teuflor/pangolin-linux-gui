# Pangolin GUI für Linux

Inoffizieller Tray-Client für [Pangolin](https://pangolin.net) unter Linux, aufgebaut wie der
offizielle [Windows-Client](https://github.com/fosrl/windows). Die eigentliche Arbeit macht die
offizielle [Pangolin-CLI](https://github.com/fosrl/cli); diese App ist eine grafische Oberfläche
darüber.

> **Status:** Prototyp. Die Unit-Tests laufen; ein echter Test mit Pangolin-Server steht noch aus.

## Funktionen

- **Tray-Icon:** orange bei Verbindung, grau ohne
- **Verbinden/Trennen** aus dem Menü oder dem Statusfenster
- **Sites-Menü** wie unter Windows: Status, Verbindungsart (Direct/Relay/Local), Endpoint,
  letzter Kontakt und Latenz je Site
- **Konten:** wechseln, hinzufügen (Login per Einmal-Code im Browser), abmelden
- **Organisationen** wechseln, auch bei laufender Verbindung
- **Statusfenster** mit Tabelle aller Sites
- **Log-Viewer** mit Suche, Auto-Refresh und Farbmarkierung
- **Einstellungen:** DNS-Optionen der CLI, Log-Level, Autostart, automatisch verbinden
- **Grafische Passwortabfrage** für die Admin-Rechte beim Verbinden

Noch nicht enthalten: Auswahl eines Exit-Nodes (die CLI kann Exit-Nodes nur interaktiv auflisten).

## Abhängigkeiten

Die GUI ist reines Python ohne pip-Pakete. Sie braucht nur Systempakete:

| Zweck | Arch Linux | Debian / Ubuntu |
|---|---|---|
| Python 3.10+ | `python` | (vorinstalliert) |
| GTK-Bindings (PyGObject) | `python-gobject` | `python3-gi` |
| GTK 3 | `gtk3` | `gir1.2-gtk-3.0` |
| Tray-Icon (AppIndicator) | `libayatana-appindicator` | `gir1.2-ayatanaappindicator3-0.1` |
| Admin-Rechte beim Verbinden | `sudo` | (vorinstalliert) |
| Pangolin-CLI | AUR `pangolin-bin` oder `get-cli.sh` | `get-cli.sh` |
| Tests (optional) | `python-pytest` | `python3-pytest` |

Die Paketlisten stehen auch in [`deps/arch.txt`](deps/arch.txt) und
[`deps/debian.txt`](deps/debian.txt); `install.sh --deps` liest sie von dort.

## Installation auf Arch Linux

Gilt auch für Manjaro, EndeavourOS und andere Arch-Ableger.

### 1. Pangolin-CLI installieren

Aus dem AUR (mit einem AUR-Helper wie `yay` oder `paru`):

```bash
yay -S pangolin-bin
```

Alternativ das offizielle Installationsskript
([Anleitung](https://docs.pangolin.net/manage/clients/install-client)):

```bash
curl -fsSL https://static.pangolin.net/get-cli.sh | bash
```

Prüfen:

```bash
pangolin version
```

### 2. Repository klonen

```bash
git clone https://github.com/Teuflor/pangolin-linux-gui.git
cd pangolin-linux-gui
```

### 3. Abhängigkeiten und Menüeintrag

```bash
./install.sh --deps
```

Das installiert per `sudo pacman -S --needed` die fehlenden Pakete aus `deps/arch.txt` und legt
einen Eintrag „Pangolin“ im Anwendungsmenü an. Ohne `--deps` zeigt das Skript nur an, was fehlt.

Von Hand geht es so:

```bash
sudo pacman -S --needed python python-gobject gtk3 libayatana-appindicator sudo
```

### Arch-spezifische Hinweise

- **sudo:** Bei einer minimalen Arch-Installation ist `sudo` oft nicht eingerichtet. Dein
  Benutzer muss `sudo` nutzen dürfen (z. B. Gruppe `wheel` und `%wheel ALL=(ALL:ALL) ALL` in
  `visudo`). Sonst schlägt *Connect* fehl, denn die Pangolin-CLI startet den Tunnel per `sudo`.
- **Tray-Icon je Desktop:**
  - **KDE Plasma:** funktioniert ohne Zusatz.
  - **GNOME:** braucht die Erweiterung *AppIndicator and KStatusNotifierItem Support*:
    `sudo pacman -S gnome-shell-extension-appindicator`, danach abmelden/anmelden und die
    Erweiterung in *Erweiterungen* aktivieren.
  - **XFCE:** Panel-Element *Statusbenachrichtigungen* bzw. *Infobereich* zum Panel hinzufügen
    (seit XFCE 4.16 Teil von `xfce4-panel`).
  - **Hyprland / Sway / andere Wayland-Compositors:** braucht eine Leiste mit Tray, z. B.
    Waybar mit dem Modul `tray`.
  - Ohne Tray öffnet die App ihr Statusfenster; Verbinden und Trennen gehen auch dort.
- **Benachrichtigungen:** Fehlermeldungen kommen als Desktop-Benachrichtigung. Unter
  Fenstermanagern ohne Benachrichtigungsdienst `dunst` oder `mako` installieren.
- **Browser für den Login:** geöffnet wird der Standardbrowser (`xdg-open`). Falls nichts
  passiert: `xdg-settings set default-web-browser firefox.desktop`.

## Installation auf Debian / Ubuntu

1. Pangolin-CLI installieren:

   ```bash
   curl -fsSL https://static.pangolin.net/get-cli.sh | bash
   ```

2. Repository klonen und installieren:

   ```bash
   git clone https://github.com/Teuflor/pangolin-linux-gui.git
   cd pangolin-linux-gui
   ./install.sh --deps
   ```

   Das installiert per `sudo apt-get` die Pakete aus `deps/debian.txt`.

3. **GNOME (Standard-Ubuntu):** Die Erweiterung *AppIndicator and KStatusNotifierItem Support*
   ist meist schon aktiv, sonst:

   ```bash
   sudo apt install gnome-shell-extension-appindicator
   ```

## Weitere Optionen von install.sh

```bash
./install.sh --autostart   # beim Anmelden im Tray starten
./install.sh --uninstall   # Menüeintrag, Icon und Autostart entfernen
```

Das Repo bleibt an seinem Ort; Menüeintrag und Autostart zeigen auf `bin/pangolin-gui` im
geklonten Ordner. Nach `git pull` ist die neue Version sofort aktiv.

## Starten

```bash
./bin/pangolin-gui            # Statusfenster öffnen, Icon im Tray
./bin/pangolin-gui --hidden   # nur Tray (für Autostart)
./bin/pangolin-gui --debug    # ausführliche Logs im Terminal
```

Ein zweiter Aufruf startet keine zweite Instanz, sondern holt das Statusfenster nach vorne.

## Testanleitung für den ersten Lauf

1. `./bin/pangolin-gui --debug` im Terminal starten. Fehler erscheinen dann dort.
2. **Anmelden:** Tray → *Log In…* (oder Verbinden im Statusfenster) → Cloud oder eigenen Server
   wählen → Code kopieren → *Open browser* → im Browser bestätigen.
3. **Organisation:** Tray → *Organization* sollte deine Organisationen zeigen.
4. **Verbinden:** Tray → *Connect*. Es erscheint ein Passwortdialog für `sudo`. Danach wechselt
   der Status über *Registering…* zu *Connected*, das Icon wird orange.
5. **Sites:** Tray → *Sites* und *Open Status…* sollten die Sites mit Latenz zeigen.
6. **Logs:** Tray → *Logs…*
7. **Trennen:** Tray → *Disconnect*.

Gegenprobe in einem Terminal: `pangolin status client` sollte dasselbe zeigen wie die GUI.

Bitte bei Problemen die Terminal-Ausgabe von `--debug` und `pangolin logs client -n 100`
festhalten.

## So funktioniert es

| Aufgabe | Umsetzung |
|---|---|
| Status | HTTP über den Unix-Socket `/var/run/olm.sock` (`GET /status`), alle 2 s abgefragt |
| Verbinden | `pangolin up client --silent`. Die CLI startet den Tunnel-Dienst per `sudo`; ohne Terminal fragt `sudo` über `bin/pangolin-gui-askpass` (GTK-Passwortdialog) |
| Trennen | `pangolin down client` |
| Konten | `~/.config/pangolin/accounts.json` (nur lesend) |
| Organisationen | REST-API `GET /api/v1/user/{id}/orgs` mit der Session der CLI |
| Anmeldung | `pangolin auth login <host>` in einem Pseudo-Terminal; die GUI zeigt den Code an |
| Einstellungen | `pangolin config set up.* …`, GUI-eigene Werte in `~/.config/pangolin-gui/` |

Das Passwort aus dem Dialog geht nur an `sudo` und wird weder gespeichert noch geloggt.
Wer ohne Passwortabfrage verbinden will, kann `pangolin` in `sudoers` freigeben; das ist aber
eine bewusste Sicherheitsentscheidung.

Details zum Aufbau stehen in [`ARCHITECTURE.md`](ARCHITECTURE.md).

## Projektstruktur

```
bin/pangolin-gui            Startskript
bin/pangolin-gui-askpass    Passwortdialog für sudo
pangolin_gui/
  app.py                    Gtk.Application und Controller
  state.py                  Polling, Zustand für die UI
  cli.py                    Aufrufe der Pangolin-CLI, Login im Pseudo-Terminal
  olm_socket.py             Client für den Tunnel-Dienst (Unix-Socket)
  api.py                    REST-API (Organisationen)
  accounts.py               Konten und Konfiguration der CLI lesen
  tray.py                   Tray-Icon und Menü
  windows/                  Status, Logs, Einstellungen, Login
tests/                      pytest
deps/arch.txt               Paketliste Arch
deps/debian.txt             Paketliste Debian/Ubuntu
install.sh                  Abhängigkeiten, Menüeintrag, Autostart
```

## Tests

```bash
sudo pacman -S python-pytest      # Arch
sudo apt install python3-pytest   # Debian/Ubuntu
python3 -m pytest
```

Die Tests brauchen weder GTK noch die Pangolin-CLI noch einen Server.

## Fehlersuche

| Problem | Lösung |
|---|---|
| `Namespace Gtk not available` | `gtk3` + `python-gobject` (Arch) bzw. `gir1.2-gtk-3.0` (Debian) fehlen |
| Kein Tray-Icon, nur Statusfenster | Desktop hat keinen Tray, siehe Hinweise oben |
| *Connect*: „Authentication failed or was cancelled“ | Passwort falsch oder Benutzer darf kein `sudo` |
| *Connect* hängt bei *Registering…* | `pangolin logs client -n 100` prüfen; Server erreichbar? |
| Organisationen bleiben leer | Session abgelaufen: Tray → *Account* → *Add Account…* |
| „No permission to access /var/run/olm.sock“ | Socket gehört root; bitte melden, mit `ls -l /var/run/olm.sock` |

## Lizenz und Marken

Pangolin und das Pangolin-Logo gehören Fossorial, Inc. Dieses Projekt ist nicht offiziell und
steht in keiner Verbindung zu Fossorial. Die Icons stammen aus dem Windows-Client
([fosrl/windows](https://github.com/fosrl/windows)).
