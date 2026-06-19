"""SQLite-Persistenz: Tokens, Track-Match-Cache, Playlist-Zuordnung, Quota."""
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta

from . import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tokens (
    service       TEXT PRIMARY KEY,         -- 'spotify' | 'youtube'
    access_token  TEXT NOT NULL,
    refresh_token TEXT,
    expires_at    INTEGER NOT NULL          -- epoch seconds
);

CREATE TABLE IF NOT EXISTS track_map (
    spotify_track_id TEXT PRIMARY KEY,
    youtube_video_id TEXT NOT NULL,
    title            TEXT,
    confidence       REAL,
    status           TEXT DEFAULT 'ok',   -- 'ok' = sicherer Treffer, 'uncertain' = gesucht, kein sicherer Treffer
    matched_at       INTEGER
);

CREATE TABLE IF NOT EXISTS playlist_map (
    spotify_playlist_id TEXT PRIMARY KEY,
    youtube_playlist_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quota_log (
    day   TEXT PRIMARY KEY,   -- YYYY-MM-DD (Pacific)
    units INTEGER NOT NULL
);
"""


@contextmanager
def _conn():
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init() -> None:
    with _conn() as con:
        con.executescript(_SCHEMA)
        # Migration: status-Spalte zu bestehenden track_map-Tabellen ergaenzen
        cols = [r["name"] for r in con.execute("PRAGMA table_info(track_map)").fetchall()]
        if "status" not in cols:
            con.execute("ALTER TABLE track_map ADD COLUMN status TEXT DEFAULT 'ok'")


# ---------- Tokens ----------
def save_token(service: str, access_token: str, refresh_token: str | None, expires_in: int) -> None:
    expires_at = int(time.time()) + int(expires_in) - 60  # 60s Puffer
    with _conn() as con:
        # refresh_token bei Google nur beim ersten Consent vorhanden -> nicht ueberschreiben mit NULL
        existing = con.execute("SELECT refresh_token FROM tokens WHERE service=?", (service,)).fetchone()
        if refresh_token is None and existing is not None:
            refresh_token = existing["refresh_token"]
        con.execute(
            "INSERT INTO tokens(service, access_token, refresh_token, expires_at) "
            "VALUES(?,?,?,?) ON CONFLICT(service) DO UPDATE SET "
            "access_token=excluded.access_token, refresh_token=excluded.refresh_token, "
            "expires_at=excluded.expires_at",
            (service, access_token, refresh_token, expires_at),
        )


def get_token(service: str) -> sqlite3.Row | None:
    with _conn() as con:
        return con.execute("SELECT * FROM tokens WHERE service=?", (service,)).fetchone()


def is_connected(service: str) -> bool:
    return get_token(service) is not None


def disconnect(service: str) -> None:
    with _conn() as con:
        con.execute("DELETE FROM tokens WHERE service=?", (service,))


# ---------- Track-Match-Cache ----------
def get_cached_match(spotify_track_id: str) -> sqlite3.Row | None:
    with _conn() as con:
        return con.execute(
            "SELECT * FROM track_map WHERE spotify_track_id=?", (spotify_track_id,)
        ).fetchone()


def save_match(spotify_track_id: str, youtube_video_id: str, title: str,
               confidence: float, status: str = "ok") -> None:
    with _conn() as con:
        con.execute(
            "INSERT INTO track_map(spotify_track_id, youtube_video_id, title, confidence, status, matched_at) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(spotify_track_id) DO UPDATE SET "
            "youtube_video_id=excluded.youtube_video_id, title=excluded.title, "
            "confidence=excluded.confidence, status=excluded.status, matched_at=excluded.matched_at",
            (spotify_track_id, youtube_video_id, title, confidence, status, int(time.time())),
        )


def clear_uncertain() -> int:
    """Loescht alle als 'uncertain' gemerkten Treffer -> werden naechstes Mal neu gesucht."""
    with _conn() as con:
        cur = con.execute("DELETE FROM track_map WHERE status='uncertain'")
        return cur.rowcount


# ---------- Playlist-Zuordnung ----------
def get_mapped_playlist(spotify_playlist_id: str) -> str | None:
    with _conn() as con:
        row = con.execute(
            "SELECT youtube_playlist_id FROM playlist_map WHERE spotify_playlist_id=?",
            (spotify_playlist_id,),
        ).fetchone()
        return row["youtube_playlist_id"] if row else None


def save_playlist_map(spotify_playlist_id: str, youtube_playlist_id: str) -> None:
    with _conn() as con:
        con.execute(
            "INSERT INTO playlist_map(spotify_playlist_id, youtube_playlist_id) VALUES(?,?) "
            "ON CONFLICT(spotify_playlist_id) DO UPDATE SET youtube_playlist_id=excluded.youtube_playlist_id",
            (spotify_playlist_id, youtube_playlist_id),
        )


# ---------- Quota ----------
def _pacific_day() -> str:
    # YouTube-Quota resettet um Mitternacht Pacific. Naeherung: UTC-8.
    now = datetime.now(timezone.utc) - timedelta(hours=8)
    return now.strftime("%Y-%m-%d")


def add_quota(units: int) -> None:
    day = _pacific_day()
    with _conn() as con:
        con.execute(
            "INSERT INTO quota_log(day, units) VALUES(?,?) "
            "ON CONFLICT(day) DO UPDATE SET units = units + excluded.units",
            (day, units),
        )


def quota_used_today() -> int:
    day = _pacific_day()
    with _conn() as con:
        row = con.execute("SELECT units FROM quota_log WHERE day=?", (day,)).fetchone()
        return row["units"] if row else 0
