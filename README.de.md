# Pangolin GUI für Linux

[English](README.md) · **Deutsch**

Inoffizieller Tray-Client für [Pangolin](https://pangolin.net) unter Linux, aufgebaut wie der
offizielle [Windows-Client](https://github.com/fosrl/windows). Die eigentliche Arbeit macht die
offizielle [Pangolin-CLI](https://github.com/fosrl/cli); diese App ist eine grafische Oberfläche
darüber.

> **Status:** frühe Version. Getestet auf einem Arch-basierten System (CachyOS) mit KDE Plasma 6
> (Wayland) gegen einen selbst gehosteten Pangolin-Server. Andere Desktops und Distributionen sind
> weniger getestet; Rückmeldungen sind willkommen.

## Funktionen

- **Tray-Icon:** orange bei Verbindung, grau ohne. **Linksklick** öffnet das Statusfenster,
  **Rechtsklick** das Menü, **Mittelklick** verbindet bzw. trennt
- **Verbinden/Trennen** aus dem Menü oder dem Statusfenster; ist man noch nicht angemeldet,
  startet der Login und danach direkt die Verbindung
- **Sites-Menü** wie unter Windows: Status, Verbindungsart (Direct/Relay/Local), Endpoint,
  letzter Kontakt und Latenz je Site. Sites der Organisation, die der Tunnel nicht nutzt, stehen
  ebenfalls dort; ein Klick erklärt den Grund (Clients verbinden sich nur mit Sites, auf denen es
  eine private Ressource gibt, die man nutzen darf)
- **Konten:** wechseln, hinzufügen (Login per Einmal-Code im Browser), abmelden
- **Organisationen** wechseln, auch bei laufender Verbindung
- **Statusfenster** mit Tabelle aller Sites
- **Log-Viewer** mit Suche, Auto-Refresh und Farbmarkierung
- **Online-Clients:** Bei bestehender Verbindung zeigt das Tray-Menü, welche anderen Geräte
  der Organisation online sind. Ein Klick kopiert deren Tunnel-IP in die Zwischenablage.
- **Einstellungen:** Sprache, DNS-Optionen der CLI, Log-Level, Autostart, automatisch verbinden
- **Mehrsprachig:** Deutsch und Englisch, weitere Sprachen per JSON-Datei
- **Verbinden ohne Passwort** über einen optionalen systemd-Dienst mit Polkit-Regel, sonst
  **grafische Passwortabfrage** für die Admin-Rechte

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
| IP in Zwischenablage (Wayland / X11) | `wl-clipboard`, `xclip` | `wl-clipboard`, `xclip` |
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
sudo pacman -S --needed python python-gobject gtk3 libayatana-appindicator sudo wl-clipboard xclip
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
./install.sh --autostart               # beim Anmelden im Tray starten
./install.sh --system-service          # Verbinden ohne Passwort (siehe unten)
./install.sh --remove-system-service   # wieder zurück zur sudo-Abfrage
./install.sh --uninstall               # Menüeintrag, Icon und Autostart entfernen
```

Das Repo bleibt an seinem Ort; Menüeintrag und Autostart zeigen auf `bin/pangolin-gui` im
geklonten Ordner. Nach `git pull` ist die neue Version sofort aktiv.

### Verbinden ohne Passwort (Systemdienst)

Den Tunnel kann nur root einrichten. Ohne weitere Einrichtung fragt die CLI deshalb bei jedem
Verbinden per `sudo` nach dem Passwort. `./install.sh --system-service` richtet stattdessen
einmalig (mit `sudo`) Folgendes ein:

| Datei | Zweck |
|---|---|
| `/usr/local/bin/pangolin` | Pangolin-CLI, root-gehörend (wird aus `~/.local/bin` verschoben; ein Paket in `/usr/bin` wird direkt genutzt) |
| `/usr/local/lib/pangolin-gui/pangolin-gui-client` | Startprogramm des Dienstes (Kopie von `system/pangolin-gui-client`) |
| `/etc/systemd/system/pangolin-gui@.service` | systemd-Dienst `pangolin-gui@<user>.service`, nicht beim Booten aktiv |
| `/etc/polkit-1/rules.d/50-pangolin-gui.rules` | erlaubt dem angemeldeten Benutzer, **nur seinen eigenen** Dienst ohne Passwort zu starten, stoppen und neu zu starten |

Danach startet *Verbinden* den Dienst per `systemctl`, *Trennen* stoppt ihn. Fehlt die
Polkit-Freigabe, fällt die GUI auf die sudo-Abfrage zurück. Beim Herunterfahren stoppt systemd
den Dienst sauber, DNS und Routen werden zurückgesetzt.

Sicherheit: Das Startprogramm läuft als root und liest nur das aktive Konto
(`accounts.json`) und die `up.*`-Einstellungen (`config.json`) aus `~/.config/pangolin/`,
und nur aus regulären Dateien des Benutzers (keine Symlinks). Es prüft jeden Wert und startet
ausschließlich `pangolin up client`, ohne Shell. Das Client-Secret steht wie beim sudo-Weg der
CLI in der Befehlszeile (für lokale Benutzer in `ps` sichtbar). Ein Programm, das unter dem
eigenen Benutzer läuft, kann damit ohne
Passwort den Tunnel ein- und ausschalten und über die eigenen Konto-Dateien das Ziel des Tunnels
ändern, aber keine anderen Befehle als root ausführen. Ein `sudoers`-Eintrag ohne Passwort ist
dagegen **nicht** zu empfehlen: Die CLI ruft `sudo sh -c "…"` auf, eine solche Freigabe würde
beliebige Befehle als root erlauben.

Nach einem Update der GUI, das `system/` ändert, `./install.sh --system-service` erneut
ausführen; nach `pangolin update` ebenso, falls die CLI dabei wieder in `~/.local/bin` landet.

## Starten

```bash
./bin/pangolin-gui            # Statusfenster öffnen, Icon im Tray
./bin/pangolin-gui --hidden   # nur Tray (für Autostart)
./bin/pangolin-gui --debug    # ausführliche Logs im Terminal
```

Ein zweiter Aufruf startet keine zweite Instanz, sondern holt das Statusfenster nach vorne.

### Tray-Icon und Klicks

Die App meldet ihr Icon selbst per D-Bus als *StatusNotifierItem* an (KDE Plasma, GNOME mit
AppIndicator-Erweiterung, XFCE, Waybar):

| Klick | Wirkung |
|---|---|
| Links | Statusfenster öffnen bzw. nach vorne holen |
| Rechts | Menü |
| Mitte | Verbinden / Trennen |

Läuft kein StatusNotifier-Dienst, nutzt die App AppIndicator. Dort öffnen Links- und
Rechtsklick das Menü; das Statusfenster erreicht man über *Open Status…* oder den Mittelklick.
Das Backend lässt sich erzwingen:

```bash
PANGOLIN_TRAY=gtk ./bin/pangolin-gui   # AppIndicator statt eigenem D-Bus-Icon
PANGOLIN_TRAY=sni ./bin/pangolin-gui   # eigenes D-Bus-Icon erzwingen
```

### Logs

Die GUI schreibt nach stderr: Start (Sprache, CLI-Pfad, Tray-Backend), geladene Konten und
Organisationen, Verbindungswechsel, Login. Mit `--debug` zusätzlich jeden CLI-Aufruf samt
Exit-Code und letzter Ausgabe sowie jeden API-Aufruf mit HTTP-Status. Passwörter, Sitzungs-Token
und Login-Codes landen nie im Log.

## Sprache

Unter *Einstellungen… → Sprache* stehen zur Wahl:

- **Systemstandard:** folgt der Desktop-Sprache (`LANGUAGE`/`LANG`, z. B. `de_DE.UTF-8` → Deutsch)
- **English**
- **Deutsch**

Die Umstellung wirkt sofort: Tray-Menü und offene Fenster werden in der neuen Sprache neu
aufgebaut. Auch der Passwortdialog für `sudo` folgt der Einstellung.

### Weitere Sprache hinzufügen

Jede Sprache ist eine Datei `pangolin_gui/locales/<code>.json`, z. B. `fr.json`:

```json
{
  "name": "Français",
  "strings": {
    "Connect": "Se connecter",
    "Version {version}": "Version {version}"
  }
}
```

Eine Vorlage mit allen Texten erzeugt das Prüfwerkzeug:

```bash
echo '{"name": "Français", "strings": {}}' > pangolin_gui/locales/fr.json
python3 tools/i18n_check.py --update   # trägt alle Texte (leer) in jede Sprachdatei ein
python3 tools/i18n_check.py            # zeigt fehlende Übersetzungen und Platzhalterfehler
```

Platzhalter wie `{version}` oder `{ip}` müssen in der Übersetzung erhalten bleiben. Fehlende
Einträge erscheinen auf Englisch. Die neue Sprache taucht automatisch in den Einstellungen auf.

## Online-Clients

Bei bestehender Verbindung gibt es im Tray das Untermenü **Online-Clients (n)**. Es listet die
anderen Geräte der aktuellen Organisation, die gerade online sind, jeweils mit Name und Tunnel-IP
(z. B. `laptop-anna · 100.90.128.7`). Bei Benutzergeräten zeigt der Tooltip den Besitzer.

- **Klick auf einen Eintrag** kopiert die IP in die Zwischenablage, mit Bestätigung als
  Benachrichtigung.
- **Aktualisieren** lädt die Liste sofort neu; sonst wird sie alle 30 Sekunden abgefragt, und nur
  solange eine Verbindung besteht.
- Das eigene Gerät wird anhand der IP der Schnittstelle `pangolin` ausgeblendet.

**Berechtigung:** Die Liste kommt aus der Pangolin-API (`/org/{orgId}/clients` und
`/org/{orgId}/user-devices`). Beide verlangen die Berechtigung *listClients*, die in Pangolin
standardmäßig Admins haben. Ohne diese Berechtigung zeigt das Menü
„Keine Berechtigung, Clients aufzulisten“. Ein Admin kann der eigenen Rolle das Recht geben.

**Zwischenablage:** Eine Tray-App hat beim Menüklick keinen Fokus. Unter Wayland setzen viele
Compositors die Zwischenablage dann nicht per GTK. Deshalb nutzt die App `wl-copy`
(Paket `wl-clipboard`) bzw. unter X11 `xclip`, wenn vorhanden; `install.sh --deps` installiert
beide.

## Testanleitung für den ersten Lauf

1. `./bin/pangolin-gui --debug` im Terminal starten. Fehler erscheinen dann dort.
2. **Anmelden:** Tray → *Log In…* (oder Verbinden im Statusfenster) → Cloud oder eigenen Server
   wählen → Code kopieren → *Open browser* → im Browser bestätigen.
3. **Organisation:** Tray → *Organization* sollte deine Organisationen zeigen.
4. **Verbinden:** Tray → *Connect*. Ohne Systemdienst erscheint ein Passwortdialog für `sudo`. Danach wechselt
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
| Verbinden | Mit Systemdienst: `systemctl start pangolin-gui@<user>.service` (ohne Passwort, siehe oben). Sonst `pangolin up client --silent`: Die CLI startet den Tunnel-Dienst per `sudo`; ohne Terminal fragt `sudo` über `bin/pangolin-gui-askpass` (GTK-Passwortdialog) |
| Trennen | Mit Systemdienst: `systemctl stop …`, sonst `pangolin down client` |
| Konten | `~/.config/pangolin/accounts.json` (nur lesend) |
| Organisationen | REST-API `GET /api/v1/user/{id}/orgs` mit der Session der CLI |
| Anmeldung | `pangolin auth login <host>` in einem Pseudo-Terminal; die GUI zeigt den Code an |
| Einstellungen | `pangolin config set up.* …`, GUI-eigene Werte in `~/.config/pangolin-gui/` |

Das Passwort aus dem Dialog geht nur an `sudo` und wird weder gespeichert noch geloggt.
Wer ohne Passwortabfrage verbinden will, nutzt den Systemdienst (`./install.sh --system-service`),
keinen `sudoers`-Eintrag.

Details zum Aufbau stehen in [`ARCHITECTURE.md`](ARCHITECTURE.md).

## Projektstruktur

```
bin/pangolin-gui            Startskript
bin/pangolin-gui-askpass    Passwortdialog für sudo
pangolin_gui/
  app.py                    Gtk.Application und Controller
  state.py                  Polling, Zustand für die UI
  cli.py                    Aufrufe der Pangolin-CLI, Login im Pseudo-Terminal
  service.py                Systemdienst-Modus: systemctl start/stop
  olm_socket.py             Client für den Tunnel-Dienst (Unix-Socket)
  api.py                    REST-API (Organisationen)
  accounts.py               Konten und Konfiguration der CLI lesen
  tray.py                   Menüinhalt (build_menu_model) und Wahl des Tray-Backends
  menu_model.py             Toolkit-neutrales Menümodell
  sni.py                    Tray-Icon per D-Bus (StatusNotifierItem + dbusmenu)
  tray_gtk.py               Fallback: AppIndicator / Gtk.StatusIcon
  i18n.py                   Übersetzungen (_() und N_())
  locales/de.json           Deutsche Texte
  clipboard.py, netinfo.py  Zwischenablage, eigene Tunnel-IP
  windows/                  Status, Logs, Einstellungen, Login
system/                     Systemdienst: Startprogramm (läuft als root), systemd-Unit, Polkit-Regel
data/icons/                 Tray-Icons (Quellen in data/icons/src/)
tools/i18n_check.py         Texte sammeln, Sprachdateien prüfen
tests/                      pytest
deps/arch.txt               Paketliste Arch
deps/debian.txt             Paketliste Debian/Ubuntu
install.sh                  Abhängigkeiten, Menüeintrag, Autostart, Systemdienst
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
| Tray-Icon fehlt oder reagiert falsch | Log-Zeile `tray backend: …` prüfen; testweise `PANGOLIN_TRAY=gtk` |
| *Connect*: „Authentication failed or was cancelled“ | Passwort falsch oder Benutzer darf kein `sudo` |
| *Connect* mit Systemdienst: „Der Tunnel-Dienst hat sich direkt nach dem Start beendet“ | `journalctl -u pangolin-gui@$USER` zeigt den Grund; nach einem GUI-Update `./install.sh --system-service` erneut ausführen |
| *Connect* hängt bei *Registering…* | `pangolin logs client -n 100` prüfen; Server erreichbar? |
| Organisationen bleiben leer | Session abgelaufen: Tray → *Account* → *Add Account…* |
| Online-Clients: „Keine Berechtigung …“ | Rolle hat kein *listClients*, siehe Abschnitt Online-Clients |
| IP wird nicht kopiert | `wl-clipboard` (Wayland) bzw. `xclip` (X11) installieren |
| Sprache wechselt nicht | *Speichern* in den Einstellungen klicken; bei „Systemstandard“ `echo $LANG` prüfen |
| „No permission to access /var/run/olm.sock“ | Socket gehört root; bitte melden, mit `ls -l /var/run/olm.sock` |

## Lizenz und Marken

Dieses Projekt steht unter der [GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0).

Pangolin und das Pangolin-Logo sind Marken von Fossorial, Inc. Dieses Projekt ist ein
inoffizieller Client, nicht von Fossorial entwickelt und steht in keiner Verbindung zu
Fossorial. Es nutzt weder das Pangolin-Logo noch Code von Fossorial; die eigentliche Arbeit
macht die separat installierte offizielle [Pangolin-CLI](https://github.com/fosrl/cli).
Die Tray-Icons sind eigene Entwürfe (Quellen in `data/icons/src/`).
