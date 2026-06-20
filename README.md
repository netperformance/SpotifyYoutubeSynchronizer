# Spotify → YouTube Sync

One-way synchronization of Spotify playlists to YouTube playlists, with a web UI.
Spotify is the source of truth: changes on YouTube **never** flow back.
If you delete something on YouTube and sync again, the Spotify state is restored.

*(Deutsche Version weiter unten / German version below.)*

## What the app does
1. Lists your Spotify playlists, numbered and sorted alphabetically.
2. For each selected playlist: finds the existing YouTube playlist (via the marker
   `[sync:spotify:<id>]` in its description) or creates a new one.
3. Web UI with single or multiple selection ("select all"), a live sync queue with
   per-playlist status, and the option to cancel a single playlist or the whole job.
4. Current, non-deprecated login mechanisms: Spotify Authorization Code,
   Google OAuth 2.0 (offline access).
5. Mirroring: missing videos are added, surplus ones (optionally) removed.
6. Matching prefers the **original audio** (Topic/official channels, duration check,
   cover/live/remix filter). Uncertain matches are NOT added automatically; they are
   listed in the UI for manual review. A checkbox lets you ignore uncertain matches.

## Honest limitations (important)
- **No 100% guarantee of the "Spotify version".** There is no official track-ID mapping
  between the services. The heuristic gets it right ~90% of the time; the rest goes to
  the review list instead of blindly adding a cover.
- **YouTube quota:** 10,000 units/day. A search costs 100, an insert 50.
  → roughly 100 new songs searchable per day. That is why there is a **cache**: once a
  track is matched it is stored (`track_map`) and costs 0 search units on the next run.
  Even uncertain/no-match results are cached so they are not searched again. Spread large
  libraries across several days; the cache survives when the daily quota is exhausted.
- The displayed quota number is a **local estimate**; Google's accounting is authoritative
  and the two can diverge. The day boundary follows real Pacific time (incl. DST).

## Setup (Windows)

> Note: The commands here are for Windows. `source ...` is Unix/macOS and does NOT work on Windows.

### 1. Create and activate a virtual environment
```bat
python -m venv .venv
```
Activate, depending on your shell:
- **cmd.exe:**  `.venv\Scripts\activate.bat`
- **PowerShell:** `.venv\Scripts\Activate.ps1`
  (if blocked, once: `Set-ExecutionPolicy -Scope Process -RemoteSigned`)

Afterwards `(.venv)` must appear before the prompt.

### 2. Install dependencies (REQUIRED, otherwise no `uvicorn`)
```bat
pip install -r requirements.txt
```
If `uvicorn` is still "not found" afterwards, start it via Python (bypasses PATH):
```bat
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 3. Create the configuration (REQUIRED before connecting)
```bat
copy .env.example .env
```
Then open `.env` in an editor and **fill in all four keys**.
> While the values are empty, "Connect Spotify" / "Connect YouTube" deliberately return
> an **HTTP 500 "CLIENT_ID missing"**. That is not a bug — enter the keys first.

## Setup macOS / Linux
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Getting the API credentials

### Spotify
1. https://developer.spotify.com/dashboard → create an app, "Web API".
2. Redirect URI exactly: `http://127.0.0.1:8000/callback/spotify`
3. Put Client ID/Secret into `.env`.

### Google / YouTube
1. https://console.cloud.google.com → create a project.
2. Enable "YouTube Data API v3".
3. Configure the OAuth consent screen, add yourself as a test user.
4. Credentials → OAuth client ID → "Web application".
5. Authorized redirect URI exactly: `http://127.0.0.1:8000/callback/youtube`
6. Put Client ID/Secret into `.env`.

## Run
```bat
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
(or `python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`)

Then open http://127.0.0.1:8000 → connect both services → pick playlists → synchronize.

## Common pitfalls
- **`'source' ... not found`** → you are on Windows; see activation above.
- **`'uvicorn' ... not found`** → forgot `pip install -r requirements.txt`, or the venv is
  not active. Alternatively `python -m uvicorn ...`.
- **HTTP 500 on `/login/spotify` or `/login/youtube`** → `.env` still empty/incomplete.
- **`redirect_uri_mismatch`** → the URI in the dashboard/cloud console must match the one
  in `.env` EXACTLY. Use `127.0.0.1` throughout, not `localhost`.
- **404 `/favicon.ico`** → harmless, ignore it.

## Notes
- The SQLite file (`sync.db`) contains OAuth tokens and the cache — never commit it to Git.
  The included `.gitignore` already excludes `.env` and `*.db`.
- The `min_confidence` slider in the UI controls how strict the original match must be.

---

# Spotify → YouTube Sync (Deutsch)

Einseitige Synchronisation von Spotify-Playlists auf YouTube-Playlists, mit Web-UI.
Spotify ist die Quelle der Wahrheit: Änderungen auf YouTube fließen **nie** zurück.
Löschst du etwas auf YouTube und synchronisierst erneut, wird der Spotify-Stand wiederhergestellt.

## Was die App tut
1. Listet deine Spotify-Playlists durchnummeriert und alphabetisch.
2. Pro ausgewählter Playlist: vorhandene YouTube-Playlist finden (über Marker
   `[sync:spotify:<id>]` in der Beschreibung) oder neu anlegen.
3. Web-UI mit Einzel- oder Mehrfachauswahl ("alle auswählen"), einer Live-Warteschlange
   mit Status pro Playlist und der Möglichkeit, einzelne Listen oder den ganzen Job abzubrechen.
4. Aktuelle, nicht-deprecated Login-Mechanismen: Spotify Authorization Code,
   Google OAuth 2.0 (offline access).
5. Spiegelung: fehlende Videos werden ergänzt, überzählige (optional) entfernt.
6. Matching bevorzugt **Original-Audio** (Topic-/Official-Kanäle, Dauer-Abgleich,
   Cover/Live/Remix-Filter). Unsichere Treffer werden NICHT automatisch übernommen,
   sondern in der UI zur manuellen Prüfung gelistet. Eine Checkbox ignoriert unsichere Treffer.

## Ehrliche Grenzen (wichtig)
- **Keine 100%-Garantie für die "Spotify-Version".** Es gibt keine offizielle
  Track-ID-Zuordnung zwischen den Diensten. Die Heuristik trifft ~90 %; der Rest
  landet in der Prüfliste statt blind ein Cover zu übernehmen.
- **YouTube-Quota:** 10.000 Einheiten/Tag. Eine Suche kostet 100, ein Hinzufügen 50.
  → ca. 100 neue Songs pro Tag suchbar. Deshalb der **Cache**: einmal gematchte
  Tracks werden gespeichert (`track_map`) und kosten beim nächsten Lauf 0 Such-Einheiten.
  Auch unsichere/nicht gefundene Ergebnisse werden gecacht und nicht erneut gesucht.
  Große Bibliotheken über mehrere Tage verteilen; bei Erschöpfung bleibt der Cache erhalten.
- Die angezeigte Quota-Zahl ist ein **lokaler Schätzwert**; maßgeblich ist Googles
  Zählung, beide können auseinanderlaufen. Der Tageswechsel folgt der echten Pacific-Zeit (inkl. Sommerzeit).

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
- Die SQLite-Datei (`sync.db`) enthält OAuth-Tokens und Cache – niemals ins Git committen.
  Die mitgelieferte `.gitignore` schließt `.env` und `*.db` bereits aus.
- `min_confidence`-Regler in der UI steuert, wie streng der Original-Match sein muss.
