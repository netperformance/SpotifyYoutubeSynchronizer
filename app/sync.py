"""Sync-Orchestrierung pro Playlist + In-Memory-Job-Tracking + Abbrechen."""
import uuid

from . import config, db, spotify, youtube, matching

# In-Memory-Jobs (Single-User-Betrieb)
JOBS: dict[str, dict] = {}
# Abbruch-Flags getrennt halten (Set ist nicht JSON-serialisierbar)
CANCEL: dict[str, dict] = {}


def new_job(playlists: list[dict]) -> str:
    """playlists: Liste von {'id':..., 'name':...} in gewuenschter Reihenfolge."""
    jid = uuid.uuid4().hex[:12]
    JOBS[jid] = {
        "id": jid,
        "state": "running",
        "log": [],
        "needs_review": [],
        "quota_used_today": db.quota_used_today(),
        "quota_limit": 10000,
        "error": None,
        "queue": [
            {"spotify_id": p["id"], "name": p.get("name") or p["id"],
             "status": "queued", "added": 0, "removed": 0,
             "cached": 0, "searched": 0, "review": 0, "ignored": 0, "error": None}
            for p in playlists
        ],
    }
    CANCEL[jid] = {"all": False, "ids": set()}
    return jid


def cancel(job_id: str, playlist_id: str | None = None) -> bool:
    c = CANCEL.get(job_id)
    if c is None:
        return False
    if playlist_id:
        c["ids"].add(playlist_id)
    else:
        c["all"] = True
    return True


def _cancelled(job_id: str, playlist_id: str) -> bool:
    c = CANCEL.get(job_id, {})
    return c.get("all") or playlist_id in c.get("ids", set())


def _log(job: dict, msg: str) -> None:
    job["log"].append(msg)


def _friendly_message(e: Exception) -> str:
    if isinstance(e, youtube.YouTubeApiError):
        return str(e)
    return f"Unerwarteter Fehler ({type(e).__name__}): {e}"


async def run_sync(job_id: str, remove_extras: bool, min_confidence: float,
                   ignore_uncertain: bool = False) -> None:
    job = JOBS[job_id]
    try:
        for item in job["queue"]:
            if CANCEL.get(job_id, {}).get("all"):
                if item["status"] == "queued":
                    item["status"] = "cancelled"
                continue
            if _cancelled(job_id, item["spotify_id"]):
                item["status"] = "cancelled"
                _log(job, f"⏹ „{item['name']}“ übersprungen (abgebrochen).")
                continue
            try:
                await _sync_one(job, job_id, item, remove_extras, min_confidence, ignore_uncertain)
            except youtube.QuotaExceeded:
                # Tageskontingent betrifft den ganzen Job, nicht nur diese Playlist -> abbrechen.
                raise
            except Exception as e:  # noqa: BLE001
                # Fehler bei genau dieser Playlist isolieren, Rest der Warteschlange läuft weiter.
                message = _friendly_message(e)
                item["status"] = "error"
                item["error"] = message
                job["failed_any"] = True
                _log(job, f"  ✗ „{item['name']}“ fehlgeschlagen: {message}")

        if CANCEL.get(job_id, {}).get("all"):
            job["state"] = "cancelled"
            _log(job, "⏹ Gesamter Sync abgebrochen.")
        elif job.get("failed_any"):
            failed_names = [it["name"] for it in job["queue"] if it["status"] == "error"]
            job["state"] = "error"
            job["error"] = ("Fehlgeschlagen: " + ", ".join(failed_names) +
                            ". Alle anderen ausgewählten Listen wurden verarbeitet. "
                            "Mit „Fehlgeschlagene erneut versuchen“ nur diese wiederholen.")
            _log(job, f"✗ {len(failed_names)} von {len(job['queue'])} Playlisten fehlgeschlagen, "
                      f"Rest wurde erfolgreich verarbeitet.")
        else:
            job["state"] = "done"
            _log(job, "✓ Alle ausgewählten Listen verarbeitet.")
    except youtube.QuotaExceeded as e:
        for it in job["queue"]:
            if it["status"] == "running":
                it["status"] = "stopped"
        job["state"] = "quota"
        job["error"] = str(e)
        _log(job, f"⚠ {e} Cache bleibt erhalten – morgen erneut „Synchronisieren“ drücken, "
                  f"erledigte Lieder werden übersprungen.")
    except Exception as e:  # noqa: BLE001
        for it in job["queue"]:
            if it["status"] == "running":
                it["status"] = "error"
        job["state"] = "error"
        job["error"] = _friendly_message(e)
        _log(job, f"✗ Fehler: {job['error']}")
    finally:
        job["quota_used_today"] = db.quota_used_today()


async def _sync_one(job, job_id, item, remove_extras, min_confidence, ignore_uncertain) -> None:
    spid = item["spotify_id"]
    item["status"] = "running"
    name = await spotify.get_playlist_name(spid)
    item["name"] = name
    _log(job, f"▶ Playlist „{name}“ …")

    tracks = await spotify.get_playlist_tracks(spid)
    _log(job, f"  {len(tracks)} Tracks aus Spotify geladen.")

    marker = config.SYNC_MARKER.format(spotify_id=spid)
    yt_pl = db.get_mapped_playlist(spid) or await youtube.find_playlist_by_marker(marker)
    if not yt_pl:
        desc = f"Automatisch synchronisiert aus Spotify. {marker}"
        yt_pl = await youtube.create_playlist(name, desc)
        _log(job, f"  YouTube-Playlist neu angelegt: {yt_pl}")
    else:
        _log(job, f"  Vorhandene YouTube-Playlist gefunden: {yt_pl}")
    db.save_playlist_map(spid, yt_pl)

    desired_video_ids: list[str] = []
    for tr in tracks:
        if _cancelled(job_id, spid):
            item["status"] = "cancelled"
            _log(job, f"  ⏹ „{name}“ während des Matchings abgebrochen.")
            job["quota_used_today"] = db.quota_used_today()
            return
        vid, conf, source, certain = await _resolve_video(tr, min_confidence)
        if source == "cache":
            item["cached"] += 1
        elif source == "search":
            item["searched"] += 1
        if certain and vid:
            desired_video_ids.append(vid)
        elif ignore_uncertain:
            item["ignored"] += 1
        else:
            item["review"] += 1
            job["needs_review"].append({
                "playlist": name, "track": f'{tr["artist"]} – {tr["name"]}',
                "spotify_track_id": tr["id"], "confidence": conf,
            })

    current = await youtube.playlist_items(yt_pl)
    current_vids = {c["video_id"] for c in current}
    desired_set = set(desired_video_ids)

    for vid in desired_video_ids:
        if _cancelled(job_id, spid):
            item["status"] = "cancelled"
            _log(job, f"  ⏹ „{name}“ beim Hinzufügen abgebrochen (Teilstand bleibt).")
            job["quota_used_today"] = db.quota_used_today()
            return
        if vid not in current_vids:
            await youtube.add_to_playlist(yt_pl, vid)
            current_vids.add(vid)
            item["added"] += 1
            job["quota_used_today"] = db.quota_used_today()

    if remove_extras:
        for it in current:
            if _cancelled(job_id, spid):
                break
            if it["video_id"] not in desired_set:
                await youtube.remove_item(it["item_id"])
                item["removed"] += 1
                job["quota_used_today"] = db.quota_used_today()

    if item["status"] != "cancelled":
        item["status"] = "done"
    _log(job, f"  ✓ „{name}“: +{item['added']} / -{item['removed']}, "
              f"{item['cached']} Cache, {item['searched']} gesucht, "
              f"{item['review']} zur Prüfung, {item['ignored']} ignoriert.")
    job["quota_used_today"] = db.quota_used_today()


async def _resolve_video(track: dict, min_confidence: float):
    """Liefert (video_id|None, confidence, source, certain).
    source: 'cache'|'search'  certain: True wenn sicherer Treffer."""
    cached = db.get_cached_match(track["id"])
    if cached:
        if cached["status"] == "ok":
            return cached["youtube_video_id"], cached["confidence"], "cache", True
        # 'uncertain' -> nicht erneut suchen, keine Quota
        return None, cached["confidence"], "cache", False

    title = f'{track["artist"]} – {track["name"]}'
    query = matching.build_query(track["name"], track["artist"])
    candidates = await youtube.search_videos(query)
    if not candidates:
        db.save_match(track["id"], "", title, 0.0, status="uncertain")
        return None, 0.0, "search", False

    durations = await youtube.videos_details([c["video_id"] for c in candidates])
    best = matching.pick_best(track, candidates, durations)
    if best and best["confidence"] >= min_confidence:
        db.save_match(track["id"], best["video_id"], title, best["confidence"], status="ok")
        return best["video_id"], best["confidence"], "search", True
    # bester Kandidat zu unsicher -> als 'uncertain' merken (mit bestem Kandidaten zur Info)
    db.save_match(track["id"], best["video_id"] if best else "", title,
                  best["confidence"] if best else 0.0, status="uncertain")
    return None, (best["confidence"] if best else 0.0), "search", False
