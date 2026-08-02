"""YouTube-Client: Google-OAuth + Data API v3 (Suche, Playlists, Items) mit Quota-Zaehlung."""
import asyncio
import html
import time
import urllib.parse

import httpx

from . import config, db

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3"

# Quota-Kosten je Methode (Stand 2026)
COST_SEARCH = 100
COST_LIST = 1
COST_WRITE = 50


def _token_error_details(response) -> str:
    try:
        data = response.json()
    except Exception:  # noqa: BLE001
        data = {}
    error = data.get("error")
    description = data.get("error_description")
    if error or description:
        detail = ", ".join(part for part in [error, description] if part)
        return f"{detail}"
    return response.text or "unbekannter Fehler"


def build_auth_url(state: str) -> str:
    params = {
        "client_id": config.GOOGLE_CLIENT_ID,
        "redirect_uri": config.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": config.YOUTUBE_SCOPES,
        "access_type": "offline",     # liefert refresh_token
        "prompt": "consent",          # erzwingt refresh_token auch bei Re-Auth
        "state": state,
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


async def exchange_code(code: str) -> None:
    if not config.GOOGLE_CLIENT_ID or not config.GOOGLE_CLIENT_SECRET:
        raise RuntimeError("GOOGLE_CLIENT_ID oder GOOGLE_CLIENT_SECRET fehlt in .env")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(TOKEN_URL, data={
            "code": code,
            "client_id": config.GOOGLE_CLIENT_ID,
            "client_secret": config.GOOGLE_CLIENT_SECRET,
            "redirect_uri": config.GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        })
        if r.status_code != 200:
            db.disconnect("youtube")
            raise RuntimeError(
                f"Google Token-Tausch fehlgeschlagen ({r.status_code}): "
                f"{_token_error_details(r)}. Bitte erneut mit YouTube verbinden."
            )
        t = r.json()
        db.save_token("youtube", t["access_token"], t.get("refresh_token"), t["expires_in"])


async def _refresh() -> None:
    tok = db.get_token("youtube")
    if not tok or not tok["refresh_token"]:
        raise RuntimeError("YouTube nicht verbunden (kein refresh_token).")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(TOKEN_URL, data={
            "refresh_token": tok["refresh_token"],
            "client_id": config.GOOGLE_CLIENT_ID,
            "client_secret": config.GOOGLE_CLIENT_SECRET,
            "grant_type": "refresh_token",
        })
        if r.status_code != 200:
            db.disconnect("youtube")
            raise RuntimeError(
                f"Google Token-Refresh fehlgeschlagen ({r.status_code}): "
                f"{_token_error_details(r)}. Bitte erneut mit YouTube verbinden."
            )
        t = r.json()
        db.save_token("youtube", t["access_token"], t.get("refresh_token"), t["expires_in"])


async def _token() -> str:
    tok = db.get_token("youtube")
    if not tok:
        raise RuntimeError("YouTube nicht verbunden.")
    if tok["expires_at"] <= int(time.time()):
        await _refresh()
        tok = db.get_token("youtube")
    return tok["access_token"]


def _classify_limit(r) -> str:
    """Klassifiziert 403/429-Fehler anhand des Antwort-Bodys.
    'quota' = Tageskontingent erschoepft (kein Retry sinnvoll),
    'rate'  = kurzfristiges Ratenlimit (mit Wartezeit erneut versuchen),
    'other' = anderer 403 (z.B. Berechtigung)."""
    t = (r.text or "").lower()
    if "dailylimitexceeded" in t or "quotaexceeded" in t:
        return "quota"
    if r.status_code == 429 or "ratelimitexceeded" in t or "userratelimitexceeded" in t:
        return "rate"
    return "other"


# Status-Codes, die typischerweise kurzlebig/transient sind (Server-Konflikt,
# ueberlastete Backends) und bei denen ein erneuter Versuch sinnvoll ist.
# 409 tritt bei playlistItems oft durch kurzzeitige Nebenlaeufigkeit auf.
_TRANSIENT_STATUS = {409, 500, 502, 503, 504}


def _friendly_error(r) -> str:
    try:
        data = r.json()
        err = data.get("error", {})
        message = err.get("message") or (err.get("errors") or [{}])[0].get("reason", "")
    except Exception:  # noqa: BLE001
        message = ""
    detail = message or (r.text or "")[:200] or "unbekannter Fehler"
    return f"YouTube-Anfrage fehlgeschlagen ({r.status_code}): {detail}"


async def _request(method: str, path: str, cost: int, *, params=None, json=None,
                   max_retries: int = 4) -> dict:
    token = await _token()
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=30) as c:
        for attempt in range(max_retries + 1):
            try:
                r = await c.request(method, f"{API}{path}", headers=headers, params=params, json=json)
            except httpx.TransportError as e:
                if attempt < max_retries:
                    await asyncio.sleep(2 ** attempt)  # 1, 2, 4, 8 Sekunden
                    continue
                raise YouTubeApiError(f"YouTube nicht erreichbar: {e}") from e

            if r.status_code == 401:
                await _refresh()
                headers["Authorization"] = f"Bearer {await _token()}"
                continue

            if r.status_code in (403, 429):
                kind = _classify_limit(r)
                if kind == "quota":
                    # Abgelehnte Anfragen kosten serverseitig keine Quota -> nicht mitzaehlen
                    raise QuotaExceeded("YouTube-Tageskontingent erschoepft.")
                if kind == "rate":
                    if attempt < max_retries:
                        await asyncio.sleep(2 ** attempt)  # 1, 2, 4, 8 Sekunden
                        continue
                    raise QuotaExceeded(
                        "YouTube-Ratenlimit anhaltend erreicht (nach mehreren Wiederholungen gestoppt).")
                # anderer 403 -> echter Fehler
                db.add_quota(cost)
                raise YouTubeApiError(_friendly_error(r), r.status_code)

            if r.status_code in _TRANSIENT_STATUS:
                # Kurzlebiger Konflikt/Backend-Fehler -> mit Backoff erneut versuchen
                if attempt < max_retries:
                    await asyncio.sleep(2 ** attempt)  # 1, 2, 4, 8 Sekunden
                    continue
                db.add_quota(cost)
                raise YouTubeApiError(_friendly_error(r), r.status_code)

            db.add_quota(cost)
            if r.status_code >= 400:
                raise YouTubeApiError(_friendly_error(r), r.status_code)
            return r.json() if r.text else {}
    raise YouTubeApiError("YouTube-Anfrage nach mehreren Wiederholungen fehlgeschlagen.")


class QuotaExceeded(RuntimeError):
    pass


class YouTubeApiError(RuntimeError):
    """Fehlgeschlagene YouTube-API-Anfrage mit lesbarer Meldung und Status-Code."""
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


# ---------- Suche / Matching-Daten ----------
async def search_videos(query: str, max_results: int = 12) -> list[dict]:
    """search.list -> Kandidaten (id, title, channel). Kostet 100 Einheiten
    (fix pro Aufruf, unabhaengig von max_results - mehr Kandidaten sind also gratis).
    Kein videoCategoryId-Filter mehr: bei kleinen/regionalen Kanaelen (Weltmusik,
    Nischengenres) ist die Kategorie-Zuordnung oft unzuverlaessig gepflegt und
    haette sonst passende Original-Audios stillschweigend ausgeschlossen -
    die Bewertung in matching.py filtert Nicht-Musik-Treffer zuverlaessiger."""
    data = await _request("GET", "/search", COST_SEARCH, params={
        "part": "snippet",
        "q": query,
        "type": "video",
        "maxResults": max_results,
    })
    out = []
    for it in data.get("items", []):
        vid = it.get("id", {}).get("videoId")
        sn = it.get("snippet", {})
        if vid:
            # YouTube liefert Titel/Kanalnamen HTML-entity-kodiert (z.B. "Don&#39;t"
            # statt "Don't") - unbedingt dekodieren, sonst zerstoert das exakte
            # Wortvergleiche im Matching (Ziffern aus "&#39;" landen sonst mitten
            # im normalisierten Text).
            out.append({"video_id": vid, "title": html.unescape(sn.get("title", "")),
                        "channel": html.unescape(sn.get("channelTitle", ""))})
    return out


async def videos_details(video_ids: list[str]) -> dict[str, int]:
    """videos.list -> Dauer in Sekunden je Video. Kostet 1 Einheit (bis 50 IDs)."""
    if not video_ids:
        return {}
    data = await _request("GET", "/videos", COST_LIST, params={
        "part": "contentDetails",
        "id": ",".join(video_ids[:50]),
    })
    res: dict[str, int] = {}
    for it in data.get("items", []):
        res[it["id"]] = _parse_iso8601(it.get("contentDetails", {}).get("duration", "PT0S"))
    return res


def _parse_iso8601(dur: str) -> int:
    import re
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", dur or "")
    if not m:
        return 0
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s


# ---------- Playlists ----------
async def find_playlist_by_marker(marker: str) -> str | None:
    """Sucht eigene Playlist, deren Beschreibung den Sync-Marker enthaelt."""
    page = None
    while True:
        params = {"part": "snippet", "mine": "true", "maxResults": 50}
        if page:
            params["pageToken"] = page
        data = await _request("GET", "/playlists", COST_LIST, params=params)
        for it in data.get("items", []):
            desc = it.get("snippet", {}).get("description", "")
            if marker in desc:
                return it["id"]
        page = data.get("nextPageToken")
        if not page:
            return None


async def create_playlist(title: str, description: str) -> str:
    data = await _request("POST", "/playlists", COST_WRITE,
                          params={"part": "snippet,status"},
                          json={"snippet": {"title": title, "description": description},
                                "status": {"privacyStatus": "private"}})
    return data["id"]


async def playlist_items(youtube_playlist_id: str) -> list[dict]:
    """Aktuelle Items: liefert (playlist_item_id, video_id)."""
    out, page = [], None
    while True:
        params = {"part": "contentDetails", "playlistId": youtube_playlist_id, "maxResults": 50}
        if page:
            params["pageToken"] = page
        data = await _request("GET", "/playlistItems", COST_LIST, params=params)
        for it in data.get("items", []):
            out.append({"item_id": it["id"],
                        "video_id": it.get("contentDetails", {}).get("videoId")})
        page = data.get("nextPageToken")
        if not page:
            return out


async def add_to_playlist(youtube_playlist_id: str, video_id: str) -> None:
    try:
        await _request("POST", "/playlistItems", COST_WRITE,
                       params={"part": "snippet"},
                       json={"snippet": {"playlistId": youtube_playlist_id,
                                         "resourceId": {"kind": "youtube#video", "videoId": video_id}}})
    except YouTubeApiError as e:
        if e.status_code == 409:
            # Trotz Wiederholungen weiter im Konflikt -> Video ist vermutlich bereits
            # in der Playlist (Wettlauf mit einem parallelen Versuch). Kein harter Fehler.
            return
        raise


async def remove_item(playlist_item_id: str) -> None:
    try:
        await _request("DELETE", "/playlistItems", COST_WRITE, params={"id": playlist_item_id})
    except YouTubeApiError as e:
        if e.status_code in (404, 409):
            # Eintrag ist bereits nicht mehr vorhanden -> Ziel ohnehin erreicht.
            return
        raise
