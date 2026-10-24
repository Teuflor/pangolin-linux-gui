# Änderungswünsche Pangolin GUI

Ergebnisse des ersten echten Tests: CachyOS, KDE Plasma 6.8.1 (Wayland), GUI-Stand `2786e90`,
Pangolin-CLI 0.19.0, selbst gehosteter Pangolin-Server 1.25. Mit der Korrektur aus Punkt 0
funktionieren Login und Verbinden; der Rechner erscheint im Dashboard online.

## Umsetzungsstand (nach Praxistest 1)

| Punkt | Stand | Umsetzung |
|---|---|---|
| 0 | erledigt, auf echtem System geprüft | `activeuserid` gelesen; genau ein Konto ohne aktives → wird per `pangolin select account` gewählt und verbunden; Login-Dialog füllt die bekannte Server-URL vor; ist die Sitzung abgelaufen, startet der Login direkt für diesen Server, danach wird verbunden |
| 1 | erledigt, auf echtem System geprüft | eigenes StatusNotifierItem per D-Bus (`sni.py`): Linksklick = Statusfenster, Rechtsklick = Menü, Mittelklick = Verbinden/Trennen; AppIndicator bleibt Fallback (`PANGOLIN_TRAY=gtk`). Rechtsklick-Menü war leer, behoben in `9356cce` (siehe Praxistest 2) |
| 2 | erledigt | „Connect“/„Disconnect“ ist ein normaler Eintrag statt Checkbox; nach jedem Klick wird das Menü aus dem echten Zustand neu gebaut; nach einem über „Connect“ gestarteten Login wird direkt verbunden |
| 3 | erledigt | „Open Status…“ steht immer oben im Menü; Statusfenster zeigt ohne Verbindung einen Hinweis |
| 4 | erledigt | kein Handlungsbedarf |
| 5 | erledigt | Ursache: abgebrochener Login wurde nicht mit `wait()` abgeholt; jetzt immer (Test mit Fake-CLI) |
| 6 | erledigt | Logzeilen für Start, Tray-Backend, Konten, Organisationen, Verbindungswechsel, jeden CLI-Aufruf (Befehl, Exit-Code, Ausgabe) und API-Aufrufe |
| 7 | war vorhanden | Einstellungen → „Lokale Routen bevorzugen, wenn verfügbar“ |

## Praxistest 2 (Stand `e0d85f7`, 2026-10-23) – erledigt

Gleiches System. Alle Punkte direkt behoben und auf echtem System geprüft:

| Punkt | Commit | Umsetzung |
|---|---|---|
| Rechtsklick auf das Tray-Icon zeigt kein Menü | `9356cce` | `sni.py` verpackte die Menüeinträge doppelt als Variant (`v(v(...))`), Plasma verwarf sie; Test prüft jetzt das Wire-Format |
| `./install.sh` nicht ausführbar | `9356cce` | Dateimodus 100755 |
| Verbinden fragt jedes Mal nach dem sudo-Passwort | `be699cf`, `63e23a3`, `9c3fce7` | optionaler Systemdienst `pangolin-gui@<user>.service` mit Polkit-Freigabe (`install.sh --system-service`); Start/Stopp ohne Passwort, DNS und Heimnetz bleiben lokal, Stoppen räumt sauber auf |
| `up.override_dns=false` wirkte beim sudo-Weg nicht | `be699cf` | die CLI gibt den Wert nicht an den root-Prozess weiter; der Systemdienst übergibt alle `up.*`-Werte explizit |

## 0. Aktives Konto wird nicht erkannt → „Connect“ startet immer wieder den Login

**Status:** erledigt (siehe Umsetzungsstand).

**Ist:** Jeder Klick auf „Connect“ fragt erneut nach der Server-URL und verlangt einen neuen
Login im Browser. `pangolin up` wird nie aufgerufen, daher entsteht kein Tunnel und kein Client
im Dashboard.

**Ursache:** `pangolin_gui/accounts.py`, `load_accounts()` liest `data.get("activeUserId")`.
Die CLI 0.19.0 schreibt den Schlüssel aber klein: `"activeuserid"`. Damit ist
`active_account` immer `None`, und `controller.connect()` leitet zu `add_account()` um.
Die Tests (`tests/test_state.py`) verwenden ebenfalls `activeUserId` und fallen deshalb nicht auf.

Nachgeprüft mit der echten Datei: 1 Konto geladen, aktives Konto erkannt: `False`.

**Soll:**
- [x] Schlüssel `activeuserid` lesen (zur Sicherheit beide Schreibweisen akzeptieren).
- [x] Tests mit der Schreibweise der aktuellen CLI.
- [x] Gibt es genau ein Konto, aber kein aktives, dieses verwenden statt den Login zu starten.
- [x] Der Login-Dialog sollte die bekannte Server-URL vorausfüllen bzw. gar nicht erst fragen,
  wenn schon ein Konto für diesen Server existiert.

## 1. Tray-Klicks: links = Statusfenster, rechts = Menü

**Ist:** Linksklick und Rechtsklick öffnen beide das Tray-Menü. Das Statusfenster lässt sich nur
über *Sites → Open Status…* öffnen, und diesen Eintrag gibt es nur bei bestehender Verbindung.
Ohne Verbindung kommt man gar nicht an das Statusfenster.

**Soll:**
- Linksklick öffnet das Statusfenster (bzw. holt es nach vorne).
- Rechtsklick öffnet das Tray-Menü.
- *Open Status…* zusätzlich als Eintrag auf oberster Ebene des Menüs, unabhängig vom
  Verbindungsstatus.

**Ursache (`pangolin_gui/tray.py`):**
- Die App nutzt `AppIndicator3` bzw. `AyatanaAppIndicator3`. Diese Bibliotheken kennen nur ein
  Menü und keinen Klick-Handler; KDE zeigt deshalb bei Linksklick das Menü. Ayatana bietet
  lediglich `set_secondary_activate_target()` für den Mittelklick.
- Der Fallback `Gtk.StatusIcon` (der `activate` kennt) funktioniert unter Wayland nicht.
- `Open Status…` wird nur im Sites-Untermenü angelegt (`_build_menu`, Block „Sites submenu“).

**Lösungsvorschlag:** Ein eigenes StatusNotifierItem per D-Bus (`Gio.DBus`) statt AppIndicator:
`Activate` (Linksklick) → `controller.open_status()`, `ContextMenu`/`Menu` (Rechtsklick) → das
bestehende Menü über `com.canonical.dbusmenu`. Mittelklick (`SecondaryActivate`) könnte
Verbinden/Trennen umschalten. AppIndicator als Fallback für Desktops ohne SNI behalten.

## 2. „Connect“ bleibt angehakt, obwohl nicht verbunden

**Ist:** Nach dem ersten Login zeigt das Menü „Disconnected“ und gleichzeitig ein angehaktes
„Connect“. Es läuft kein Tunnel (`pangolin status client`: „No client is currently running“),
es wurde auch kein `pangolin up` gestartet, und `--debug` loggt keinen Fehler. Ein weiterer Klick
auf den angehakten Eintrag würde `disconnect()` auslösen statt zu verbinden.

**Vermutete Ursache:** `Gtk.CheckMenuItem` schaltet beim Klick selbst um. `controller.connect()`
leitet ohne aktives Konto zu `add_account()` weiter und setzt keinen Übergangszustand; die
Menü-Signatur ändert sich danach nicht (weiterhin „Disconnected“), das Menü wird nicht neu
aufgebaut und der Haken bleibt stehen.

**Soll:**
- Der Haken spiegelt immer den echten Zustand; bei Abbruch/Fehler/Login-Umweg Menü neu aufbauen.
- Besser ein normales `Gtk.MenuItem` „Connect“/„Disconnect“ statt Checkbox.
- Nach erfolgreichem Login, der über „Connect“ gestartet wurde, direkt verbinden.

## 3. Statusfenster und „Sites“ ohne Verbindung

Ohne Verbindung gibt es kein „Sites“-Menü und damit gar keinen Weg zum Statusfenster (siehe 1).
Das Statusfenster sollte immer erreichbar sein und ohne Verbindung einen Hinweis zeigen.

## 4. Erledigt: Socket-Rechte `/var/run/olm.sock`

Geprüft bei laufendem Tunnel: `srw-rw-rw- root root`. Jeder lokale User darf lesen (und
schreiben), die GUI zeigt den Status korrekt als verbunden. Kein Handlungsbedarf in der GUI.

## 5. Zombie-Prozess nach dem Verbinden

Nach dem Verbinden bleibt ein `[pangolin] <defunct>` als Kind des GUI-Prozesses zurück.
Ein von der GUI gestarteter Prozess wird nicht mit `wait()` abgeholt (vermutlich der
Login-`Popen` in `cli.LoginSession` oder der per `nohup` abgelöste `up`-Start).

## 6. `--debug` gibt nichts aus

Mit `pangolin-gui --debug` erschien im Terminal auch beim Login und Verbinden keine einzige
Logzeile. Entweder loggen die Module kaum, oder das Logging wird nicht konfiguriert.

## 7. Vorschlag: „Lokale Routen bevorzugen“ in den Einstellungen

Eine Site gibt ein Subnetz frei, das zugleich das lokale Netz des Rechners ist. Der Tunnel legt
diese Route ohne Metrik an, damit läuft im eigenen Netz der lokale Verkehr (z. B. zum lokalen
DNS-Server) über den Tunnel. Die CLI hat dafür `--prefer-local-routes`;
das sollte in den Einstellungen als Schalter erscheinen.

## Hinweis: Dashboard

Per CLI mit Benutzerkonto verbundene Rechner erscheinen im Dashboard unter
**Clients → User Devices**, nicht bei den Machine Clients. Die GUI könnte im Statusfenster den
Gerätenamen anzeigen, unter dem der Rechner im Dashboard steht.

## Upstream (Pangolin-CLI, nicht GUI)

Die CLI startet den Tunnel als `pangolin up client … --secret <secret>`. Das Client-Secret ist
damit für jeden lokalen User in `ps` sichtbar.
