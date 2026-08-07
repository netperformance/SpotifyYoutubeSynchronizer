"""Matching-Heuristik: findet die Original-Audio-Version statt Cover/Live/Remix.

Garantie ist technisch unmoeglich (keine offizielle Spotify->YouTube-Zuordnung).
Strategie:
 - Topic-Kanaele ("... - Topic") sind YouTubes auto-generierte Original-Audios
   (Content-ID), das Naechste an der "Spotify-Version" -> stark bevorzugen.
 - VEVO / Official Artist Channel -> bevorzugen.
 - Dauer-Abgleich gegen Spotify duration_ms (Toleranz) -> starkes Signal.
 - Cover/Live/Karaoke/Remix/Sped-up etc. abwerten (ausser im Original-Titel enthalten).
 - Liegt der beste Score unter MIN_CONFIDENCE -> als "unsicher" zurueck (manuelle Freigabe).

Normalisierung ist unicode-bewusst (siehe _norm): Titel/Kuenstler/Kanal koennen in
jeder Sprache/Schrift vorliegen (Latein mit Akzenten, Kyrillisch, Griechisch,
Arabisch, Hebraeisch, Chinesisch, Japanisch, Koreanisch, ...) - es werden nur
Satzzeichen/Symbole entfernt, alle Buchstaben und Ziffern jeder Sprache bleiben
erhalten.
"""
import difflib
import re
import unicodedata

DURATION_TOLERANCE_S = 7          # +/- Sekunden gegenueber Spotify
MIN_CONFIDENCE = 0.55             # darunter: manuelle Freigabe noetig

# Bei jeder inhaltlichen Aenderung an score_candidate/_norm/_NEG etc. hochzaehlen.
# Als 'uncertain' zwischengespeicherte Treffer mit einer aelteren Version werden
# beim naechsten Sync automatisch neu gesucht (siehe sync._resolve_video) - ohne
# dass man manuell "Unsichere neu suchen lassen" klicken muss. 'ok'-Treffer sind
# davon bewusst ausgenommen (sonst wuerde jede Aenderung die ganze Bibliothek neu
# durchsuchen und massiv Quota verbrauchen); nur unerkannte Songs profitieren
# automatisch von Verbesserungen.
ALGO_VERSION = 5

_NEG = ["cover", "remix", "live", "karaoke", "instrumental", "tribute",
        "sped up", "speed up", "slowed", "reverb", "8d audio", "nightcore",
        "reaction", "lyrics video", "lyric video", "guitar", "piano version",
        "acoustic", "mashup", "parody", "ai cover"]

# "Offiziell" in vielen Sprachen - viele regionale Labels/Vertriebe (z.B.
# franko-afrikanische Musik) markieren "offizielles Video" nur im TITEL
# ("Clip Officiel"), nicht ueber Kanalnamen wie VEVO/"Topic"/"Official". Ohne
# diese Pruefung bekommt so ein Kanal (z.B. ein Label-Channel wie "OKELEDO")
# gar keinen Kanaltyp-Bonus, obwohl der Titel die Offizialitaet klar angibt.
_OFFICIAL_TITLE_MARKERS = [
    "official",     # englisch
    "officiel",     # franzoesisch (officiel/officielle)
    "oficial",      # spanisch/portugiesisch
    "offiziell",    # deutsch
    "ufficiale",    # italienisch
    "resmi",        # tuerkisch
    "官方",          # chinesisch
    "공식",          # koreanisch
    "رسمي",         # arabisch
]

# Klammerpaare inkl. asiatischer/typografischer Varianten (z.B. in chinesischen/
# japanischen Videotiteln: "（Official MV）", "【歌詞付き】", "「Live」" ...)
_BRACKETS = re.compile(r"[\(\[（【「《][^\)\]）】」》]*[\)\]）】」》]")

# Gerade vs. typografische Apostrophe/Akzente, die als Apostroph missbraucht
# werden (z.B. "N'to", "Rock 'n' Roll", "O'Brien").
_APOSTROPHES = "'’‘`´"


def _norm(s: str, strip_brackets: bool = True) -> str:
    """Unicode-sichere Normalisierung fuer Vergleich/Substring-Suche.
    Behaelt Buchstaben und Ziffern aus JEDER Schrift (nicht nur a-z/aeoeuess),
    entfernt nur Interpunktion/Symbole. Ohne das wuerden z.B. chinesische,
    arabische, hebraeische oder kyrillische Titel komplett zu Leerzeichen
    zerfallen und nie mehr matchen.
    strip_brackets=False laesst Klammerinhalte stehen - wichtig fuer die
    Negativbegriff-Erkennung, da Marker wie "(Cover)"/"(Live)" ueblicherweise
    genau dort stehen."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)   # Vollbreite Zeichen etc. vereinheitlichen
    s = s.casefold()
    if strip_brackets:
        s = _BRACKETS.sub(" ", s)
    # Apostrophe LOESCHEN statt durch Leerzeichen ersetzen: "N'to" soll zu "nto"
    # werden (wie die Kuenstlerschreibweise "NTO"), nicht zu "n to" - sonst reisst
    # ein Apostroph ein einzelnes Wort in zwei Tokens auseinander und Substring-/
    # Wortvergleiche schlagen fehl, obwohl es derselbe Name ist.
    for ch in _APOSTROPHES:
        s = s.replace(ch, "")
    kept = [ch if unicodedata.category(ch)[0] in ("L", "N") else " " for ch in s]
    return re.sub(r"\s+", " ", "".join(kept)).strip()


def _fold_accents(s: str) -> str:
    """Entfernt Akzente von lateinischen Buchstaben (é->e, ñ->n, ü->u, ...) als
    Fallback-Vergleich - YouTube-Titel schreiben Akzente bei franz./span./
    portugies. Namen nicht immer konsequent (z.B. "Rosalia" statt "Rosalía").
    Nicht-lateinische Schriften (Chinesisch, Arabisch, ...) haben keine
    Kombinationszeichen und bleiben dadurch unveraendert."""
    decomposed = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _contains(needle: str, haystack: str) -> bool:
    """Substring-Check mit Akzent-Fallback in beide Richtungen."""
    if not needle:
        return False
    if needle in haystack:
        return True
    return _fold_accents(needle) in _fold_accents(haystack)


def build_query(track_name: str, artist: str) -> str:
    return f"{artist} {track_name}".strip()


# Trennt eine anhaengende Versions-Angabe ab, z.B. "... - Radio Edit",
# "... - Bachata Version", "... - Extended Mix". Spotify haengt solche
# Zusaetze oft direkt (ohne Klammern) an den Titel an, aber viele YouTube-
# Uploads nennen sie im Titel gar nicht, obwohl es dieselbe Originalaufnahme
# ist - ein optionales Wort (z.B. das Genre) plus eines der Schluesselwoerter
# am Textende.
_VERSION_SUFFIX_RE = re.compile(r"\s+(?:\S+\s+)?(version|edit|mix|remaster(?:ed)?|remix)$")


def _strip_version_suffix(name_n: str) -> tuple[str, str | None]:
    m = _VERSION_SUFFIX_RE.search(name_n)
    if not m:
        return name_n, None
    return name_n[: m.start()].strip(), m.group(0).strip()


def _title_match_score(name_variants: list[str], nt: str, nt_full: str) -> float:
    for name_n in name_variants:
        if name_n and _contains(name_n, nt):
            return 0.35
    for name_n in name_variants:
        if name_n and _token_overlap(name_n, nt_full) >= 0.6:
            return 0.20
    # Letzter Fallback: unscharfer Wortvergleich fuer abweichende Transliterationen
    # (z.B. Arabisch->Latein ohne einheitlichen Standard). Schwaecheres Signal als
    # exakte Wortueberlappung, daher niedrigerer Bonus.
    for name_n in name_variants:
        if name_n and _fuzzy_token_overlap(name_n, nt_full) >= 0.6:
            return 0.15
    return 0.0


_CLEAN_MARKERS = ["clean", "radio edit", "radio version"]
_EXPLICIT_MARKERS = ["explicit"]


def score_candidate(track: dict, cand: dict, video_duration_s: int | None) -> float:
    """0..1 – wie gut passt der Kandidat zur Spotify-Version."""
    title = cand["title"]
    channel = cand.get("channel", "")
    nt, nc = _norm(title), _norm(channel)
    nt_full = _norm(title, strip_brackets=False)   # fuer Negativbegriffe wie "(Cover)"
    # Kanaltyp-Marker ("- Topic", "VEVO", "Official") sind feste, von YouTube
    # vergebene ASCII-Suffixe/-Woerter - dafuer roh vergleichen (casefold reicht),
    # da _norm den trennenden Bindestrich in " - Topic" entfernen wuerde.
    channel_raw = channel.casefold()
    track_name_n = _norm(track["name"])
    # Alle Mitwirkenden pruefen, nicht nur den Hauptkuenstler: bei Kollabo-Tracks
    # (sehr haeufig z.B. bei Afrobeats/Reggaeton/Bachata/Kizomba) wird der
    # YouTube-Topic-Kanal manchmal unter dem Feature-Kuenstler statt dem laut
    # Spotify fuehrenden Kuenstler angelegt.
    artists_n = [a for a in (_norm(x) for x in (track.get("artists") or [track["artist"]])) if a]
    orig = _norm(track["name"] + " " + " ".join(track.get("artists", [])))

    score = 0.0

    # Titel enthaelt Songnamen (mit Akzent-Fallback: "Rosalía" vs. "Rosalia").
    # Fallback nutzt nt_full (Klammerinhalte erhalten): Versions-Hinweise wie
    # "(Bachata Version)"/"(Remix)" stehen auf YouTube oft in Klammern UND sind
    # zugleich Teil des eigentlichen Songnamens - anders als reines Rauschen
    # ("(Official Video)") duerfen sie hier nicht verloren gehen, sonst reisst
    # das den Titel auseinander (z.B. "Amiga Mía - Bachata Version" landet bei
    # "Amiga Mía - Artist X x Artist Y (Bachata Version) | Original-Artist" ohne
    # Klammerinhalt nur noch bei 2 von 4 Wort-Treffern statt 4 von 4).
    # Zusaetzlich ein zweiter Versuch mit abgetrennter Versions-Angabe (siehe
    # _strip_version_suffix): Spotify haengt "- Radio Edit"/"- Bachata Version"
    # oft OHNE Klammern an, aber viele YouTube-Titel nennen das gar nicht,
    # obwohl es dieselbe Originalaufnahme ist.
    core_name_n, version_qualifier = _strip_version_suffix(track_name_n)
    name_variants = [track_name_n] if core_name_n == track_name_n else [track_name_n, core_name_n]
    score += _title_match_score(name_variants, nt, nt_full)
    if version_qualifier and version_qualifier in nt_full:
        score += 0.05  # Versions-Angabe steht sogar woertlich im Kandidatentitel

    # Kuenstler (irgendeiner der Mitwirkenden) im Titel oder Kanal - beide
    # Seiten gleich normalisiert, sonst schlaegt der Vergleich bei
    # Sonderzeichen wie Apostrophen fehl (z.B. Kanal "Oliver N'Goma - Topic"
    # vs. Kuenstler "Oliver N'Goma"), plus Akzent-Fallback wie beim Titel.
    artist_in_title = any(_contains(a, nt) for a in artists_n)
    artist_in_channel = any(_contains(a, nc) for a in artists_n)
    if artist_in_title or artist_in_channel:
        score += 0.25

    # Kanaltyp: starkes Signal fuer Original-Audio - ABER ein "- Topic"-Kanal
    # bestaetigt nur "automatisch erzeugtes Original-Audio", nicht zwingend
    # die Kuenstler-Identitaet: kleine/regionale Kuenstler landen oft auf
    # generischen Sammel-Kanaelen wie "Various Artists - Topic" oder
    # "<Release> - Topic" ohne den Kuenstlernamen -> dort nur abgeschwaechten
    # Bonus vergeben, vollen Bonus nur wenn der Kanalname den Kuenstler nennt.
    if channel_raw.endswith("- topic"):
        score += 0.30 if artist_in_channel else 0.12
    elif "vevo" in channel_raw or "official" in channel_raw:
        score += 0.22
    elif any(nc == a or _fold_accents(nc) == _fold_accents(a) for a in artists_n):
        # Kanalname IST (normalisiert, mit Akzent-Fallback) der Kuenstlername -
        # sehr uebliches Muster bei unabhaengigen/kleinen Kuenstlern, die ihren
        # Kanal einfach nach sich selbst benennen, ohne "VEVO"/"Official"/"Topic"
        # im Namen. Akzent-Fallback noetig, da Kanalnamen Akzente oft weglassen
        # (z.B. Kanal "Sidiki Diabate" vs. Kuenstler "Sidiki Diabaté").
        # Kein YouTube-verifiziertes Signal wie Topic/VEVO, aber ein starkes
        # Indiz fuer den eigenen Kanal des Kuenstlers.
        score += 0.20

    # "Offiziell" steht bei vielen regionalen Labels/Vertrieben nur im TITEL,
    # nicht im Kanalnamen (z.B. franko-afrikanische Musik: "Clip Officiel" auf
    # einem Label-Kanal ohne "VEVO"/"Official"/"Topic" im Namen). Eigenstaendig
    # von obigem Kanaltyp-Bonus, da es ein anderes Signal ist (Titel-Aussage
    # statt Kanal-Branding) - beide zusammen bestaetigen sich gegenseitig.
    if any(m in nt_full for m in _OFFICIAL_TITLE_MARKERS):
        score += 0.15

    # Dauer-Abgleich
    if video_duration_s and track.get("duration_ms"):
        diff = abs(video_duration_s - track["duration_ms"] / 1000)
        if diff <= DURATION_TOLERANCE_S:
            score += 0.25
        elif diff <= DURATION_TOLERANCE_S * 3:
            score += 0.08
        else:
            score -= 0.15        # deutlich andere Laenge -> wohl andere Version

    # Negativbegriffe abwerten (nur wenn NICHT im Original-Titel/-Kuenstler);
    # nt_full behaelt Klammerinhalte, da Marker wie "(Cover)" ueblicherweise dort stehen
    for neg in _NEG:
        if neg in nt_full and neg not in orig:
            score -= 0.30

    # Explicit/Clean-Version-Mismatch: Spotify markiert explizite Tracks;
    # eine als "Clean"/"Radio Edit" gekennzeichnete Version ist dann meist die
    # zensierte Variante mit abweichendem Text -> nicht die Original-Version.
    if track.get("explicit") and any(m in nt_full for m in _CLEAN_MARKERS):
        score -= 0.15
    elif track.get("explicit") is False and any(m in nt_full for m in _EXPLICIT_MARKERS):
        score -= 0.15

    return max(0.0, min(1.0, score))


def _token_overlap(a: str, b: str) -> float:
    sa, sb = set(a.split()), set(b.split())
    if not sa:
        return 0.0
    return len(sa & sb) / len(sa)


def _fuzzy_token_overlap(a: str, b: str) -> float:
    """Wie _token_overlap, aber ein Wort aus a zaehlt auch als Treffer, wenn es
    einem Wort aus b nur SEHR AEHNLICH ist (nicht exakt gleich). Wichtig fuer
    Transliterationen aus nicht-lateinischen Schriften (v.a. Arabisch), wo es
    keine einheitliche Umschrift gibt - z.B. "Qasayed" vs. "Qassayed" oder
    "Kel" vs. "Kol" fuer denselben arabischen Titel. Nur Woerter ab 5 Zeichen
    werden fuzzy verglichen (kuerzere Woerter haben zu haeufig hohe Aehnlichkeit
    rein zufaellig, z.B. "cat"/"car" - das wuerde zu viele falsche Treffer geben)."""
    wa, wb = a.split(), b.split()
    sb = set(wb)
    if not wa:
        return 0.0
    hits = 0
    for w in wa:
        if w in sb:
            hits += 1
        elif len(w) >= 5 and any(
            len(x) >= 5 and difflib.SequenceMatcher(None, w, x).ratio() >= 0.75 for x in wb
        ):
            hits += 1
    return hits / len(wa)


def rank_candidates(track: dict, candidates: list[dict], durations: dict[str, int]) -> list[dict]:
    """Alle Kandidaten mit Score, absteigend sortiert."""
    ranked = []
    for c in candidates:
        sc = score_candidate(track, c, durations.get(c["video_id"]))
        ranked.append({"video_id": c["video_id"], "title": c["title"],
                       "channel": c.get("channel", ""), "confidence": round(sc, 3)})
    ranked.sort(key=lambda x: x["confidence"], reverse=True)
    return ranked


def pick_best(track: dict, candidates: list[dict], durations: dict[str, int]) -> dict | None:
    """Bester Kandidat mit Score. None, wenn keine Kandidaten."""
    ranked = rank_candidates(track, candidates, durations)
    return ranked[0] if ranked else None
