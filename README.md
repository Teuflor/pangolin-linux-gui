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

## Installation

Entwickelt unter Ubuntu 24.04; andere Debian-basierte Distributionen sollten genauso funktionieren.

### 1. Pangolin-CLI installieren

Nach der [offiziellen Anleitung](https://docs.pangolin.net/manage/clients/install-client):

```bash
curl -fsSL https://static.pangolin.net/get-cli.sh | bash
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

Das installiert per `sudo apt` die fehlenden Pakete (`python3-gi`, `gir1.2-gtk-3.0`,
`gir1.2-ayatanaappindicator3-0.1`) und legt einen Eintrag „Pangolin“ im Anwendungsmenü an.

Weitere Optionen:

```bash
./install.sh --autostart   # beim Anmelden im Tray starten
./install.sh --uninstall   # Menüeintrag, Icon und Autostart entfernen
```

### Tray-Icon unter GNOME

GNOME (Standard-Ubuntu) zeigt Tray-Icons nur mit der Erweiterung
*AppIndicator and KStatusNotifierItem Support*. Unter Ubuntu ist sie meist schon aktiv, sonst:

```bash
sudo apt install gnome-shell-extension-appindicator
```

KDE, XFCE, Cinnamon und MATE zeigen Tray-Icons ohne Zusatz. Gibt es keinen Tray, öffnet die App
stattdessen ihr Statusfenster.

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
install.sh                  Abhängigkeiten, Menüeintrag, Autostart
```

## Tests

```bash
sudo apt install python3-pytest
python3 -m pytest
```

## Lizenz und Marken

Pangolin und das Pangolin-Logo gehören Fossorial, Inc. Dieses Projekt ist nicht offiziell und
steht in keiner Verbindung zu Fossorial. Die Icons stammen aus dem Windows-Client
([fosrl/windows](https://github.com/fosrl/windows)).
