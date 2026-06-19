"""Spotify-Client: OAuth (Authorization Code) + Lesen von Playlists/Tracks."""
import base64
import time
import urllib.parse

import httpx

from . import config, db

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"


def build_auth_url(state: str) -> str:
    params = {
        "client_id": config.SPOTIFY_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": config.SPOTIFY_REDIRECT_URI,
        "scope": config.SPOTIFY_SCOPES,
        "state": state,
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


def _basic_auth() -> str:
    raw = f"{config.SPOTIFY_CLIENT_ID}:{config.SPOTIFY_CLIENT_SECRET}".encode()
    return base64.b64encode(raw).decode()


async def exchange_code(code: str) -> None:
    if not config.SPOTIFY_CLIENT_ID or not config.SPOTIFY_CLIENT_SECRET:
        raise RuntimeError("SPOTIFY_CLIENT_ID oder SPOTIFY_CLIENT_SECRET fehlt in .env")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            TOKEN_URL,
            headers={"Authorization": f"Basic {_basic_auth()}"},
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": config.SPOTIFY_REDIRECT_URI,
            },
        )
        if r.status_code != 200:
            raise RuntimeError(f"Spotify Token-Tausch fehlgeschlagen ({r.status_code}): {r.text}")
        t = r.json()
        db.save_token("spotify", t["access_token"], t.get("refresh_token"), t["expires_in"])


async def _refresh() -> None:
    tok = db.get_token("spotify")
    if not tok or not tok["refresh_token"]:
        raise RuntimeError("Spotify nicht verbunden.")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            TOKEN_URL,
            headers={"Authorization": f"Basic {_basic_auth()}"},
            data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]},
        )
        r.raise_for_status()
        t = r.json()
        db.save_token("spotify", t["access_token"], t.get("refresh_token"), t["expires_in"])


async def _token() -> str:
    tok = db.get_token("spotify")
    if not tok:
        raise RuntimeError("Spotify nicht verbunden.")
    if tok["expires_at"] <= int(time.time()):
        await _refresh()
        tok = db.get_token("spotify")
    return tok["access_token"]


async def _get(path: str, params: dict | None = None) -> dict:
    token = await _token()
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{API}{path}", headers={"Authorization": f"Bearer {token}"}, params=params)
        if r.status_code == 401:
            await _refresh()
            token = (await _token())
            r = await c.get(f"{API}{path}", headers={"Authorization": f"Bearer {token}"}, params=params)
        r.raise_for_status()
        return r.json()


async def list_playlists() -> list[dict]:
    """Alle Playlists des Nutzers, alphabetisch sortiert (case-insensitive)."""
    out: list[dict] = []
    offset = 0
    while True:
        data = await _get("/me/playlists", {"limit": 50, "offset": offset})
        for p in data.get("items", []):
            if not p:
                continue
            out.append({
                "id": p["id"],
                "name": p["name"],
                "tracks_total": p.get("tracks", {}).get("total", 0),
                "owner": p.get("owner", {}).get("display_name"),
            })
        if data.get("next"):
            offset += 50
        else:
            break
    out.sort(key=lambda x: (x["name"] or "").casefold())
    return out


async def get_playlist_name(spotify_playlist_id: str) -> str:
    data = await _get(f"/playlists/{spotify_playlist_id}", {"fields": "name"})
    return data.get("name", "Playlist")


async def get_playlist_tracks(spotify_playlist_id: str) -> list[dict]:
    """Tracks einer Playlist. Liefert Name, Hauptkuenstler, alle Kuenstler, Dauer."""
    out: list[dict] = []
    offset = 0
    fields = "items(track(id,name,duration_ms,is_local,artists(name))),next"
    while True:
        data = await _get(
            f"/playlists/{spotify_playlist_id}/tracks",
            {"limit": 100, "offset": offset, "fields": fields, "additional_types": "track"},
        )
        for item in data.get("items", []):
            tr = item.get("track")
            if not tr or tr.get("is_local") or not tr.get("id"):
                continue
            artists = [a["name"] for a in tr.get("artists", []) if a.get("name")]
            out.append({
                "id": tr["id"],
                "name": tr["name"],
                "artists": artists,
                "artist": artists[0] if artists else "",
                "duration_ms": tr.get("duration_ms", 0),
            })
        if data.get("next"):
            offset += 100
        else:
            break
    return out
