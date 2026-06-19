"""Zentrale Konfiguration, geladen aus der .env-Datei."""
import os
from dotenv import load_dotenv

load_dotenv()


def _req(name: str) -> str:
    val = os.getenv(name, "").strip()
    return val


SPOTIFY_CLIENT_ID = _req("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = _req("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = _req("SPOTIFY_REDIRECT_URI") or "http://127.0.0.1:8000/callback/spotify"

GOOGLE_CLIENT_ID = _req("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = _req("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = _req("GOOGLE_REDIRECT_URI") or "http://127.0.0.1:8000/callback/youtube"

SECRET_KEY = _req("SECRET_KEY") or "dev-only-change-me"
DB_PATH = _req("DB_PATH") or "sync.db"

SPOTIFY_SCOPES = "playlist-read-private playlist-read-collaborative"
# Manage-Scope erlaubt Anlegen/Aendern/Loeschen von Playlists und -Items.
YOUTUBE_SCOPES = "https://www.googleapis.com/auth/youtube"

# Marker, der in die YouTube-Playlist-Beschreibung geschrieben wird,
# damit die Zuordnung Spotify-Playlist -> YT-Playlist wiederfindbar ist.
SYNC_MARKER = "[sync:spotify:{spotify_id}]"
