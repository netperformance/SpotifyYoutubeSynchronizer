"""Optionale lokale KI-Unterstuetzung: bewertet unsichere Treffer per kleinem,
lokal laufendem LLM (Qwen3-1.7B, GGUF via llama.cpp, komplett offline im
eigenen Prozess - keine Daten verlassen den Rechner).

Nur ein Tie-Breaker fuer Faelle, die die Heuristik (siehe matching.py) nicht
sicher entscheiden kann - kein Ersatz dafuer. Schlaegt bei jedem Problem
(Pakete fehlen, Modell fehlt, Absturz, Timeout) leise fehl (liefert None),
damit die normale Heuristik-Entscheidung ohne KI weiterhin funktioniert.
"""
import asyncio
import re
from pathlib import Path

from . import config

# Ab dieser Konfidenz gilt ein vom LLM bestaetigter Treffer als "sicher" -
# unabhaengig vom urspruenglichen (zu niedrigen) heuristischen Score, der
# den Track ueberhaupt erst als "unsicher" eingestuft hat.
LLM_CONFIRMED_CONFIDENCE = 0.80

_llm = None
_lock = asyncio.Lock()

# Qwen3 ist ein "Thinking"-Modell: eine harte Grammatik, die sofort ab dem ersten
# Token nur Ziffern/"none" erlaubt (kein Denk-Freiraum), macht die Antworten
# unzuverlaessig (das Modell "raet" dann eher, statt wirklich zu vergleichen -
# empirisch getestet: verwirft dann sogar eindeutig richtige Treffer). Ein kurz
# gehaltenes Denk-Budget hilft ebenfalls nicht: das Modell haelt sich bei 1.7B
# kaum an Kuerze-Vorgaben und bricht dann mitten im Fazit ab, bevor die Endzeile
# geschrieben wird - liefert dann ebenfalls kein verwertbares Ergebnis.
# Erst ein GROSSZUEGIGES Denk-Budget liefert zuverlaessig korrekte UND
# vollstaendige Antworten (getestet inkl. Faellen, in denen KEIN Kandidat passt -
# das Modell schreibt dann "ANSWER: none" statt faelschlich einen zu waehlen).
# Kostet ca. 10-20s pro Song auf einer normalen CPU - das ist der Preis fuer
# Verlaesslichkeit bei diesem Modell; die KI ist bewusst optional (Checkbox) und
# lohnt sich nur fuer Songs, die die Heuristik ohnehin nicht sicher einordnet.
_MAX_TOKENS = 800
_ANSWER_RE = re.compile(r"answer\s*:\s*(\d+|none)", re.IGNORECASE)

_SYSTEM_PROMPT = """You match a Spotify track to the correct YouTube video from a list of \
search-result candidates. Real YouTube titles are messy - watch for these patterns:
- "Artist A x Artist B" or "Artist A & Artist B" means a collaboration, not a different song.
- A trailing "| Original Artist" or "(originally by X)" credits the original songwriter, not \
the uploading channel/performer - it does not mean the wrong song.
- Parenthetical qualifiers like "(Bachata Version)", "(Remix)", "(Acoustic)", "(Sped Up)" are \
part of the song's identity ONLY if the Spotify title also has that qualifier; otherwise they \
usually mean a different, unwanted version.
- Ignore purely decorative tags like "(Official Video)", "(Lyrics)", "(HD)", "(4K)" - they \
don't affect whether a candidate is the right song.
- A candidate that is clearly a cover, live performance, reaction, karaoke, or tutorial NOT \
matching the Spotify version is wrong even if the title looks similar.
Evaluate every candidate, then finish with EXACTLY one final line in the format \
"ANSWER: <number>" naming the single best-matching candidate, or "ANSWER: none" if no \
candidate is confidently the correct track. At most one candidate can be correct."""


def is_configured() -> bool:
    """True wenn die noetigen Pakete installiert sind. Sagt nichts darueber aus,
    ob das Modell schon heruntergeladen ist - das prueft _model_path()/_load()."""
    try:
        import llama_cpp  # noqa: F401
    except ImportError:
        return False
    return True


def _model_path() -> Path:
    return Path(config.LLM_MODELS_DIR) / config.LLM_FILENAME


def model_ready() -> bool:
    return is_configured() and _model_path().exists()


# In-Memory-Download-Fortschritt (Single-User-Betrieb, wie sync.JOBS) - die UI
# pollt download_status() fuer einen echten Fortschrittsbalken statt nur
# "laedt ..." anzuzeigen und stumm zu warten.
_DOWNLOAD_STATE: dict = {"status": "idle", "downloaded": 0, "total": 0, "error": None}


def download_status() -> dict:
    return dict(_DOWNLOAD_STATE)


async def download_model() -> None:
    """Laedt das GGUF-Modell direkt per Streaming-HTTP-Request herunter (kein
    Blockieren des Servers, echter Fortschritt in Bytes ueber _DOWNLOAD_STATE
    abrufbar). Schreibt zuerst in eine .part-Datei und benennt erst nach
    vollstaendigem, erfolgreichem Download um - eine abgebrochene Datei sieht so
    nie faelschlich wie ein fertiges Modell aus."""
    import httpx

    dest = _model_path()
    if dest.exists():
        _DOWNLOAD_STATE.update(status="done", downloaded=0, total=0, error=None)
        return
    if _DOWNLOAD_STATE["status"] == "downloading":
        return  # laeuft schon

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    url = f"https://huggingface.co/{config.LLM_REPO_ID}/resolve/main/{config.LLM_FILENAME}"
    _DOWNLOAD_STATE.update(status="downloading", downloaded=0, total=0, error=None)
    try:
        async with httpx.AsyncClient(timeout=None, follow_redirects=True) as c:
            async with c.stream("GET", url) as r:
                r.raise_for_status()
                _DOWNLOAD_STATE["total"] = int(r.headers.get("content-length") or 0)
                with open(tmp, "wb") as f:
                    async for chunk in r.aiter_bytes(1024 * 1024):
                        f.write(chunk)
                        _DOWNLOAD_STATE["downloaded"] += len(chunk)
        tmp.replace(dest)
        _DOWNLOAD_STATE.update(status="done")
    except Exception as e:  # noqa: BLE001
        tmp.unlink(missing_ok=True)
        _DOWNLOAD_STATE.update(status="error", error=str(e))


def _load():
    import os
    from llama_cpp import Llama
    path = _model_path()
    if not path.exists():
        raise RuntimeError(f"KI-Modell nicht gefunden: {path}")
    return Llama(model_path=str(path), n_ctx=4096, n_threads=os.cpu_count(), verbose=False)


def _get_llm():
    global _llm
    if _llm is None:
        _llm = _load()
    return _llm


def _format_duration(seconds: int | None) -> str:
    if not seconds:
        return "unknown"
    return f"{seconds // 60}:{seconds % 60:02d}"


def _build_prompt(track: dict, candidates: list[dict], durations: dict[str, int]) -> str:
    track_dur = _format_duration(round((track.get("duration_ms") or 0) / 1000) or None)
    track_line = f'Spotify track: "{track["artist"]} - {track["name"]}" (duration {track_dur})'
    cand_lines = "\n".join(
        f'{i}. title="{c["title"]}" channel="{c.get("channel", "")}" '
        f'duration={_format_duration(durations.get(c["video_id"]))}'
        for i, c in enumerate(candidates)
    )
    return f"{track_line}\n\nCandidates:\n{cand_lines}"


def _parse_reply(text: str, n: int) -> int | None:
    """Nimmt das LETZTE 'ANSWER: <n|none>' im Text (falls das Modell doch mehrfach
    rumeiert). Kein Treffer bzw. Index ausserhalb des Kandidatenbereichs -> None
    (sicherer Fallback, kein Rateergebnis)."""
    matches = _ANSWER_RE.findall(text or "")
    if not matches:
        return None
    last = matches[-1].lower()
    if last == "none":
        return None
    idx = int(last)
    return idx if 0 <= idx < n else None


def _rerank_sync(track: dict, candidates: list[dict], durations: dict[str, int]) -> int | None:
    llm = _get_llm()
    prompt = _build_prompt(track, candidates, durations)
    out = llm.create_chat_completion(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        max_tokens=_MAX_TOKENS,
        temperature=0.0,
    )
    text = out["choices"][0]["message"]["content"] or ""
    return _parse_reply(text, len(candidates))


async def rerank(track: dict, candidates: list[dict], durations: dict[str, int]) -> int | None:
    """Liefert den Index des vom LLM gewaehlten Kandidaten oder None (kein sicherer
    Treffer bzw. KI nicht verfuegbar/fehlgeschlagen). Serialisiert ueber einen Lock,
    da ein einzelnes lokales Modell nicht sinnvoll parallel genutzt werden kann;
    laeuft in einem Thread, damit die FastAPI-Event-Loop nicht blockiert."""
    if not candidates or not model_ready():
        return None
    try:
        async with _lock:
            return await asyncio.to_thread(_rerank_sync, track, candidates, durations)
    except Exception:  # noqa: BLE001
        return None
