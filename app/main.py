"""FastAPI-App: OAuth-Flows, REST-API fuer die UI, Auslieferung der Web-UI."""
import secrets
from pathlib import Path

from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.responses import RedirectResponse, FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import config, db, spotify, youtube, sync

app = FastAPI(title="Spotify → YouTube Sync")
STATIC = Path(__file__).resolve().parent.parent / "static"

# Sehr einfacher CSRF-State-Speicher (Single-User, lokal)
_states: set[str] = set()


@app.on_event("startup")
def _startup() -> None:
    db.init()


# ---------------- OAuth ----------------
@app.get("/login/spotify")
def login_spotify():
    if not config.SPOTIFY_CLIENT_ID:
        raise HTTPException(500, "SPOTIFY_CLIENT_ID fehlt in .env")
    state = secrets.token_urlsafe(16)
    _states.add(state)
    return RedirectResponse(spotify.build_auth_url(state))


@app.get("/callback/spotify")
async def callback_spotify(code: str | None = None, state: str | None = None, error: str | None = None):
    if error:
        return RedirectResponse(f"/?error=spotify_{error}")
    if not code or state not in _states:
        raise HTTPException(400, "Ungueltiger State/Code.")
    _states.discard(state)
    try:
        await spotify.exchange_code(code)
    except Exception as e:  # noqa: BLE001
        return PlainTextResponse(f"Spotify-Verbindung fehlgeschlagen:\n\n{e}", status_code=400)
    return RedirectResponse("/?connected=spotify")


@app.get("/login/youtube")
def login_youtube():
    if not config.GOOGLE_CLIENT_ID:
        raise HTTPException(500, "GOOGLE_CLIENT_ID fehlt in .env")
    state = secrets.token_urlsafe(16)
    _states.add(state)
    return RedirectResponse(youtube.build_auth_url(state))


@app.get("/callback/youtube")
async def callback_youtube(code: str | None = None, state: str | None = None, error: str | None = None):
    if error:
        return RedirectResponse(f"/?error=youtube_{error}")
    if not code or state not in _states:
        raise HTTPException(400, "Ungueltiger State/Code.")
    _states.discard(state)
    try:
        await youtube.exchange_code(code)
    except Exception as e:  # noqa: BLE001
        return PlainTextResponse(f"YouTube-Verbindung fehlgeschlagen:\n\n{e}", status_code=400)
    return RedirectResponse("/?connected=youtube")


@app.post("/api/disconnect/{service}")
def disconnect(service: str):
    if service not in ("spotify", "youtube"):
        raise HTTPException(404)
    db.disconnect(service)
    return {"ok": True}


# ---------------- API ----------------
@app.get("/api/status")
def status():
    return {
        "spotify": db.is_connected("spotify"),
        "youtube": db.is_connected("youtube"),
        "quota_used_today": db.quota_used_today(),
        "quota_limit": 10000,
    }


@app.get("/api/playlists")
async def playlists():
    if not db.is_connected("spotify"):
        raise HTTPException(401, "Spotify nicht verbunden.")
    items = await spotify.list_playlists()
    # durchnummeriert + alphabetisch (Sortierung in spotify.list_playlists)
    return [{"index": i + 1, **p} for i, p in enumerate(items)]


@app.post("/api/sync")
async def start_sync(req: Request, bg: BackgroundTasks):
    if not (db.is_connected("spotify") and db.is_connected("youtube")):
        raise HTTPException(401, "Beide Dienste muessen verbunden sein.")
    body = await req.json()
    playlists = body.get("playlists") or []
    if not playlists:
        raise HTTPException(400, "Keine Playlist ausgewaehlt.")
    remove_extras = bool(body.get("remove_extras", True))
    min_conf = float(body.get("min_confidence", 0.55))
    ignore_uncertain = bool(body.get("ignore_uncertain", False))

    job_id = sync.new_job(playlists)
    bg.add_task(sync.run_sync, job_id, remove_extras, min_conf, ignore_uncertain)
    return {"job_id": job_id}


@app.post("/api/reset-uncertain")
def reset_uncertain():
    n = db.clear_uncertain()
    return {"ok": True, "cleared": n}


@app.post("/api/sync/{job_id}/cancel")
async def cancel_sync(job_id: str, req: Request):
    body = {}
    try:
        body = await req.json()
    except Exception:  # noqa: BLE001
        pass
    playlist_id = body.get("playlist_id")
    if not sync.cancel(job_id, playlist_id):
        raise HTTPException(404, "Job unbekannt.")
    return {"ok": True, "scope": playlist_id or "all"}


@app.get("/api/sync/{job_id}")
def sync_status(job_id: str):
    job = sync.JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job unbekannt.")
    return JSONResponse(job)


# ---------------- UI ----------------
@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
