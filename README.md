# Spotify → YouTube Sync

One-way synchronization of Spotify playlists to YouTube playlists, with a web UI.
Spotify is the source of truth: changes on YouTube **never** flow back.
If you delete something on YouTube and sync again, the Spotify state is restored.

*(Deutsche Version weiter unten / German version below.)*

## What the app does
1. Lists your Spotify playlists, numbered and sorted alphabetically. Selection and all
   sync settings (confidence slider, checkboxes) are remembered in the browser between
   visits.
2. For each selected playlist: finds the existing YouTube playlist (via the marker
   `[sync:spotify:<id>]` in its description) or creates a new one.
3. Web UI with single or multiple selection ("select all" toggle), a live sync queue with
   per-playlist status, and the option to cancel a single playlist or the whole job. A
   failure in one playlist no longer blocks the rest of the queue; failed playlists can be
   retried individually with one click.
4. Current, non-deprecated login mechanisms: Spotify Authorization Code,
   Google OAuth 2.0 (offline access).
5. Mirroring: missing videos are added, surplus ones (optionally) removed. Raising or
   lowering the confidence slider re-evaluates already-known matches for free (no new
   YouTube search) and adjusts the mirror accordingly on the next sync.
6. Matching prefers the **original audio** (Topic/official channels, duration check,
   cover/live/remix filter, collab-aware artist matching, multilingual "official" markers).
   Fully Unicode-aware: works with Chinese, Arabic, Hebrew, Cyrillic, Greek, and accented
   Latin scripts, not just ASCII. Uncertain matches are NOT added automatically; they are
   listed on the "Missing songs" page for manual review instead.
   When the matching logic itself improves, previously-uncertain tracks are automatically
   re-checked on the next sync (no manual reset needed).
7. **"Missing songs" page** (`/review`): a persistent, always-available overview of every
   track that couldn't be confidently matched, grouped by playlist, with a direct YouTube
   search link and a per-song "recheck" button (targeted re-search, without resetting or
   re-syncing the whole library).
8. **Optional local AI assist** (opt-in checkbox, off by default): a small local LLM
   (Qwen3-1.7B, running fully offline via `llama-cpp-python`, no data leaves your machine)
   acts as a tie-breaker for tracks the heuristic can't confidently place. See
   [Optional: local AI matching](#optional-local-ai-matching) below.

## Honest limitations (important)
- **No 100% guarantee of the "Spotify version".** There is no official track-ID mapping
  between the services. The heuristic (plus optional AI assist) gets most matches right;
  the rest goes to the review list instead of blindly adding a cover.
- **YouTube quota:** 10,000 units/day. A search costs 100, an insert 50.
  → roughly 100 new songs searchable per day. That is why there is a **cache**: once a
  track is matched it is stored (`track_map`) and costs 0 search units on the next run.
  Even uncertain/no-match results are cached so they are not searched again. Spread large
  libraries across several days; the cache survives when the daily quota is exhausted, and
  the sync automatically resumes where it left off (including across a quota-exhaustion
  pause) rather than starting over.
- The displayed quota number is a **local estimate**; Google's accounting is authoritative
  and the two can diverge. The day boundary follows real Pacific time (incl. DST).
- **The optional AI assist is slow by design (~10-20s per uncertain track on a normal
  CPU).** A smaller/faster prompting strategy was tested and found unreliable (it
  occasionally confirmed clearly wrong matches); a larger "thinking" budget was the only
  approach that was consistently correct in testing, including correctly saying "no match"
  when appropriate. It is opt-in for exactly this reason.

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
The "Missing songs" tab (`/review`) always shows tracks that couldn't be confidently
matched, across all previously-synced playlists — no need to re-run a full sync to see it.

## Optional: local AI matching
`requirements.txt` already includes `llama-cpp-python` (small package, prebuilt CPU wheel,
no compiler needed — see the `--extra-index-url` line at the top of `requirements.txt`).
The model itself is **not** downloaded automatically:
1. In the UI, check "KI-Unterstützung für unsichere Treffer nutzen" (AI assist).
2. If the model isn't downloaded yet, a link appears to fetch it (~1.3 GB,
   `Qwen3-1.7B-Instruct`, Apache-2.0 license, from Hugging Face — one-time download with a
   live progress bar, cached under `models/`).
3. From then on, tracks the heuristic can't confidently match are additionally checked by
   the local model before being left for manual review. It never phones home — inference
   runs entirely on your machine.

This is opt-in and off by default because it is noticeably slower (~10-20s per uncertain
track) than the pure heuristic. Configuration (model choice, download location) can be
overridden via `LLM_REPO_ID` / `LLM_FILENAME` / `LLM_MODELS_DIR` in `.env` if you want to
try a different GGUF model.

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
  The included `.gitignore` already excludes `.env`, `*.db`, and the AI model (`models/`).
- The `min_confidence` slider in the UI controls how strict the original match must be.
  Changing it re-evaluates cached matches immediately (in both directions) without
  spending YouTube quota; only tracks still unresolved after that trigger a new search.

---

# Spotify → YouTube Sync (Deutsch)

Einseitige Synchronisation von Spotify-Playlists auf YouTube-Playlists, mit Web-UI.
Spotify ist die Quelle der Wahrheit: Änderungen auf YouTube fließen **nie** zurück.
Löschst du etwas auf YouTube und synchronisierst erneut, wird der Spotify-Stand wiederhergestellt.

## Was die App tut
1. Listet deine Spotify-Playlists durchnummeriert und alphabetisch. Auswahl und alle
   Sync-Einstellungen (Trefferqualitäts-Regler, Checkboxen) werden im Browser über
   Besuche hinweg gemerkt.
2. Pro ausgewählter Playlist: vorhandene YouTube-Playlist finden (über Marker
   `[sync:spotify:<id>]` in der Beschreibung) oder neu anlegen.
3. Web-UI mit Einzel- oder Mehrfachauswahl ("alle auswählen" als echter Toggle), einer
   Live-Warteschlange mit Status pro Playlist und der Möglichkeit, einzelne Listen oder den
   ganzen Job abzubrechen. Ein Fehler bei einer Playlist blockiert nicht mehr die restliche
   Warteschlange; fehlgeschlagene Playlisten lassen sich gezielt mit einem Klick erneut
   versuchen.
4. Aktuelle, nicht-deprecated Login-Mechanismen: Spotify Authorization Code,
   Google OAuth 2.0 (offline access).
5. Spiegelung: fehlende Videos werden ergänzt, überzählige (optional) entfernt. Den
   Trefferqualitäts-Regler hoch- oder runterzuziehen bewertet bereits bekannte Treffer
   kostenlos neu (ohne neue YouTube-Suche) und passt die Spiegelung beim nächsten Sync
   entsprechend an.
6. Matching bevorzugt **Original-Audio** (Topic-/Official-Kanäle, Dauer-Abgleich,
   Cover/Live/Remix-Filter, Kollab-fähiger Künstler-Abgleich, mehrsprachige
   "offiziell"-Erkennung). Vollständig Unicode-fähig: funktioniert mit Chinesisch,
   Arabisch, Hebräisch, Kyrillisch, Griechisch und akzentuiertem Latein, nicht nur ASCII.
   Unsichere Treffer werden NICHT automatisch übernommen, sondern auf der "Fehlende
   Lieder"-Seite zur manuellen Prüfung gelistet.
   Verbessert sich die Matching-Logik selbst, werden zuvor unsichere Treffer beim nächsten
   Sync automatisch neu geprüft (kein manuelles Zurücksetzen nötig).
7. **"Fehlende Lieder"-Seite** (`/review`): eine dauerhaft verfügbare Übersicht aller
   Songs, die nicht sicher zugeordnet werden konnten, gruppiert nach Playlist, mit
   direktem YouTube-Suchlink und einem "Neu prüfen"-Button pro Song (gezielte
   Einzelsuche, ohne die ganze Bibliothek zurückzusetzen oder neu zu synchronisieren).
8. **Optionale lokale KI-Unterstützung** (Checkbox, standardmäßig aus): ein kleines,
   lokal laufendes LLM (Qwen3-1.7B, komplett offline über `llama-cpp-python`, keine Daten
   verlassen den Rechner) dient als Tie-Breaker für Songs, die die Heuristik nicht sicher
   zuordnen kann. Siehe [Optional: lokales KI-Matching](#optional-lokales-ki-matching)
   unten.

## Ehrliche Grenzen (wichtig)
- **Keine 100%-Garantie für die "Spotify-Version".** Es gibt keine offizielle
  Track-ID-Zuordnung zwischen den Diensten. Die Heuristik (plus optionale KI-Unterstützung)
  trifft die meisten Treffer richtig; der Rest landet in der Prüfliste statt blind ein
  Cover zu übernehmen.
- **YouTube-Quota:** 10.000 Einheiten/Tag. Eine Suche kostet 100, ein Hinzufügen 50.
  → ca. 100 neue Songs pro Tag suchbar. Deshalb der **Cache**: einmal gematchte
  Tracks werden gespeichert (`track_map`) und kosten beim nächsten Lauf 0 Such-Einheiten.
  Auch unsichere/nicht gefundene Ergebnisse werden gecacht und nicht erneut gesucht.
  Große Bibliotheken über mehrere Tage verteilen; bei Erschöpfung bleibt der Cache erhalten,
  und der Sync macht automatisch dort weiter, wo er aufgehört hat (auch über eine
  Quota-Pause hinweg), statt von vorn zu beginnen.
- Die angezeigte Quota-Zahl ist ein **lokaler Schätzwert**; maßgeblich ist Googles
  Zählung, beide können auseinanderlaufen. Der Tageswechsel folgt der echten Pacific-Zeit (inkl. Sommerzeit).
- **Die optionale KI-Unterstützung ist bewusst langsam (~10-20s pro unsicherem Song auf
  einer normalen CPU).** Eine schnellere Prompt-Strategie wurde getestet und als
  unzuverlässig verworfen (sie hat gelegentlich eindeutig falsche Treffer bestätigt); ein
  großzügigeres Denk-Budget war beim Testen die einzige durchgehend korrekte Variante,
  inklusive korrektem "kein Treffer" wo angebracht. Genau deshalb ist sie optional.

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
Der Tab "Fehlende Lieder" (`/review`) zeigt jederzeit Songs, die nicht sicher zugeordnet
werden konnten, über alle bereits synchronisierten Playlisten hinweg – dafür ist kein
erneuter voller Sync nötig.

## Optional: lokales KI-Matching
`requirements.txt` enthält bereits `llama-cpp-python` (kleines Paket, fertiges CPU-Wheel,
kein Compiler nötig – siehe die `--extra-index-url`-Zeile am Anfang von
`requirements.txt`). Das Modell selbst wird **nicht** automatisch heruntergeladen:
1. In der UI die Checkbox "KI-Unterstützung für unsichere Treffer nutzen" anhaken.
2. Ist das Modell noch nicht heruntergeladen, erscheint ein Link dafür (~1,3 GB,
   `Qwen3-1.7B-Instruct`, Apache-2.0-Lizenz, von Hugging Face – einmaliger Download mit
   sichtbarem Fortschrittsbalken, liegt danach unter `models/`).
3. Ab dann werden Songs, die die Heuristik nicht sicher zuordnen kann, zusätzlich vom
   lokalen Modell geprüft, bevor sie zur manuellen Prüfung landen. Es telefoniert nie
   nach Hause – die Auswertung läuft komplett auf deinem Rechner.

Das ist bewusst optional und standardmäßig aus, weil es spürbar langsamer ist (~10-20s
pro unsicherem Song) als die reine Heuristik. Konfiguration (Modellwahl, Speicherort) lässt
sich über `LLM_REPO_ID` / `LLM_FILENAME` / `LLM_MODELS_DIR` in `.env` überschreiben, falls
du ein anderes GGUF-Modell ausprobieren willst.

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
  Die mitgelieferte `.gitignore` schließt `.env`, `*.db` und das KI-Modell (`models/`) bereits aus.
- `min_confidence`-Regler in der UI steuert, wie streng der Original-Match sein muss.
  Eine Änderung bewertet zwischengespeicherte Treffer sofort neu (in beide Richtungen)
  ohne YouTube-Quota zu verbrauchen; nur danach weiterhin unsichere Songs lösen eine
  neue Suche aus.
