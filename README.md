# Spotify → YouTube Sync

Einseitige Synchronisation von Spotify-Playlists auf YouTube-Playlists, mit Web-UI.
Spotify ist die Quelle der Wahrheit: Änderungen auf YouTube fließen **nie** zurück.
Löschst du etwas auf YouTube und synchronisierst erneut, wird der Spotify-Stand wiederhergestellt.

## Was die App tut
1. Listet deine Spotify-Playlists durchnummeriert und alphabetisch.
2. Pro ausgewählter Playlist: vorhandene YouTube-Playlist finden (über Marker
   `[sync:spotify:<id>]` in der Beschreibung) oder neu anlegen.
3. Web-UI mit Einzel- oder Mehrfachauswahl ("alle auswählen").
4. Aktuelle, nicht-deprecated Login-Mechanismen: Spotify Authorization Code,
   Google OAuth 2.0 (offline access).
5. Spiegelung: fehlende Videos werden ergänzt, überzählige (optional) entfernt.
6. Matching bevorzugt **Original-Audio** (Topic-/Official-Kanäle, Dauer-Abgleich,
   Cover/Live/Remix-Filter). Unsichere Treffer werden NICHT automatisch übernommen,
   sondern in der UI zur manuellen Prüfung gelistet.

## Ehrliche Grenzen (wichtig)
- **Keine 100%-Garantie für die "Spotify-Version".** Es gibt keine offizielle
  Track-ID-Zuordnung zwischen den Diensten. Die Heuristik trifft ~90 %; der Rest
  landet in der Prüfliste statt blind ein Cover zu übernehmen.
- **YouTube-Quota:** 10.000 Einheiten/Tag. Eine Suche kostet 100, ein Hinzufügen 50.
  → ca. 100 neue Songs pro Tag suchbar. Deshalb der **Cache**: einmal gematchte
  Tracks werden gespeichert (`track_map`) und kosten beim nächsten Lauf 0 Such-Einheiten.
  Große Bibliotheken über mehrere Tage verteilen; bei Erschöpfung bleibt der Cache erhalten.

## Setup (Windows)

> Hinweis: Die hier gezeigten Befehle sind für Windows. `source ...` ist Unix/macOS und
> funktioniert unter Windows NICHT.

### 1. Virtuelle Umgebung anlegen und aktivieren
```bat
python -m venv .venv
```
Aktivieren – je nach Shell:
- **cmd.exe:**  `.venv\Scripts\activate.bat`
- **PowerShell:** `.venv\Scripts\Activate.ps1`
  (bei Sperre einmalig: `Set-ExecutionPolicy -Scope Process -RemoteSigned`)

Vor der Eingabezeile muss danach `(.venv)` stehen.

### 2. Abhängigkeiten installieren (PFLICHT, sonst kein `uvicorn`)
```bat
pip install -r requirements.txt
```
Wird `uvicorn` danach trotzdem "nicht gefunden", starte es über Python (umgeht PATH):
```bat
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 3. Konfiguration anlegen (PFLICHT vor dem Verbinden)
```bat
copy .env.example .env
```
Dann `.env` im Editor öffnen und **alle vier Schlüssel ausfüllen**.
> Solange die Werte leer sind, liefert "Spotify verbinden" bzw. "YouTube verbinden"
> bewusst einen **HTTP 500 "CLIENT_ID fehlt"**. Das ist kein Bug – erst Schlüssel eintragen.

## Setup macOS / Linux
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## API-Zugangsdaten besorgen

### Spotify
1. https://developer.spotify.com/dashboard → App anlegen, "Web API".
2. Redirect URI exakt: `http://127.0.0.1:8000/callback/spotify`
3. Client ID/Secret in `.env` eintragen.

### Google / YouTube
1. https://console.cloud.google.com → Projekt anlegen.
2. "YouTube Data API v3" aktivieren.
3. OAuth-Zustimmungsbildschirm konfigurieren, dich als Testnutzer eintragen.
4. Anmeldedaten → OAuth-Client-ID → "Webanwendung".
5. Autorisierte Redirect-URI exakt: `http://127.0.0.1:8000/callback/youtube`
6. Client ID/Secret in `.env` eintragen.

## Starten
```bat
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
(oder `python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`)

Dann http://127.0.0.1:8000 öffnen → beide Dienste verbinden → Playlists wählen → synchronisieren.

## Häufige Stolpersteine
- **`'source' ... nicht gefunden`** → du bist unter Windows; siehe Aktivierung oben.
- **`'uvicorn' ... nicht gefunden`** → `pip install -r requirements.txt` vergessen,
  oder venv nicht aktiv. Alternativ `python -m uvicorn ...`.
- **HTTP 500 bei `/login/spotify` oder `/login/youtube`** → `.env` noch leer/unvollständig.
- **`redirect_uri_mismatch`** → die URI in Dashboard/Cloud-Console muss ZEICHENGENAU
  mit der in `.env` übereinstimmen. Durchgehend `127.0.0.1` verwenden, nicht `localhost`.
- **404 `/favicon.ico`** → harmlos, ignorieren.

## Hinweise
- Die SQLite-Datei (`sync.db`) enthält Tokens und Cache – nicht ins Git committen.
- `min_confidence`-Regler in der UI steuert, wie streng der Original-Match sein muss.
