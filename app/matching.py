"""Matching-Heuristik: findet die Original-Audio-Version statt Cover/Live/Remix.

Garantie ist technisch unmoeglich (keine offizielle Spotify->YouTube-Zuordnung).
Strategie:
 - Topic-Kanaele ("... - Topic") sind YouTubes auto-generierte Original-Audios
   (Content-ID), das Naechste an der "Spotify-Version" -> stark bevorzugen.
 - VEVO / Official Artist Channel -> bevorzugen.
 - Dauer-Abgleich gegen Spotify duration_ms (Toleranz) -> starkes Signal.
 - Cover/Live/Karaoke/Remix/Sped-up etc. abwerten (ausser im Original-Titel enthalten).
 - Liegt der beste Score unter MIN_CONFIDENCE -> als "unsicher" zurueck (manuelle Freigabe).
"""
import re

DURATION_TOLERANCE_S = 7          # +/- Sekunden gegenueber Spotify
MIN_CONFIDENCE = 0.55             # darunter: manuelle Freigabe noetig

_NEG = ["cover", "remix", "live", "karaoke", "instrumental", "tribute",
        "sped up", "speed up", "slowed", "reverb", "8d audio", "nightcore",
        "reaction", "lyrics video", "lyric video", "guitar", "piano version",
        "acoustic", "mashup", "parody", "ai cover"]


def _norm(s: str) -> str:
    s = s.casefold()
    s = re.sub(r"[\(\[].*?[\)\]]", " ", s)        # Klammerinhalte weg
    s = re.sub(r"[^a-z0-9äöüß ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def build_query(track_name: str, artist: str) -> str:
    return f"{artist} {track_name}".strip()


def score_candidate(track: dict, cand: dict, video_duration_s: int | None) -> float:
    """0..1 – wie gut passt der Kandidat zur Spotify-Version."""
    title = cand["title"]
    channel = cand.get("channel", "")
    nt, nc = _norm(title), channel.casefold()
    track_name_n = _norm(track["name"])
    artist_n = _norm(track["artist"])
    orig = (track["name"] + " " + " ".join(track.get("artists", []))).casefold()

    score = 0.0

    # Titel enthaelt Songnamen
    if track_name_n and track_name_n in nt:
        score += 0.35
    elif track_name_n and _token_overlap(track_name_n, nt) >= 0.6:
        score += 0.20

    # Kuenstler im Titel oder Kanal
    if artist_n and (artist_n in nt or artist_n in nc):
        score += 0.25

    # Kanaltyp: starkes Signal fuer Original-Audio
    if nc.endswith("- topic"):
        score += 0.30
    elif "vevo" in nc or "official" in nc:
        score += 0.22

    # Dauer-Abgleich
    if video_duration_s and track.get("duration_ms"):
        diff = abs(video_duration_s - track["duration_ms"] / 1000)
        if diff <= DURATION_TOLERANCE_S:
            score += 0.25
        elif diff <= DURATION_TOLERANCE_S * 3:
            score += 0.08
        else:
            score -= 0.15        # deutlich andere Laenge -> wohl andere Version

    # Negativbegriffe abwerten (nur wenn NICHT im Original-Titel/-Kuenstler)
    for neg in _NEG:
        if neg in nt and neg not in orig:
            score -= 0.30

    return max(0.0, min(1.0, score))


def _token_overlap(a: str, b: str) -> float:
    sa, sb = set(a.split()), set(b.split())
    if not sa:
        return 0.0
    return len(sa & sb) / len(sa)


def pick_best(track: dict, candidates: list[dict], durations: dict[str, int]) -> dict | None:
    """Bester Kandidat mit Score. None, wenn keine Kandidaten."""
    best = None
    for c in candidates:
        sc = score_candidate(track, c, durations.get(c["video_id"]))
        if best is None or sc > best["confidence"]:
            best = {"video_id": c["video_id"], "title": c["title"],
                    "channel": c.get("channel", ""), "confidence": round(sc, 3)}
    return best
