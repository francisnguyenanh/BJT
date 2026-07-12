# -*- coding: utf-8 -*-
"""Storage backend for progress state + generated passages.

Cloud Run instances are stateless (local disk is wiped on restart/scale),
so this module auto-detects the environment and switches backend:
  - On Cloud Run (the `K_SERVICE` env var is always set there): Firestore.
  - Locally (no `K_SERVICE`): flat JSON files under data/, zero setup.

Every other module (progress.py, passage_generator.py, app.py) goes through
here instead of touching files/Firestore directly.
"""

import glob
import json
import os
from datetime import datetime, timezone

_ON_CLOUD_RUN = bool(os.getenv("K_SERVICE"))

_PROGRESS_COLLECTION = "bjt_state"
_PROGRESS_DOC_ID = "progress"
_PASSAGES_COLLECTION = "bjt_passages"
_LIFESTYLE_STATE_DOC_ID = "lifestyle"
_LIFESTYLE_ANALYSIS_COLLECTION = "bjt_lifestyle_analysis"
_TTS_BUCKET = os.getenv("BJT_TTS_BUCKET", "feednotebooklm-bjt-tts-cache")

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_PROGRESS_PATH = os.path.join(_DATA_DIR, "progress.json")
_PASSAGES_DIR = os.path.join(_DATA_DIR, "passages")
_LIFESTYLE_STATE_PATH = os.path.join(_DATA_DIR, "lifestyle_state.json")
_LIFESTYLE_ANALYSIS_DIR = os.path.join(_DATA_DIR, "lifestyle_analysis")
_TTS_CACHE_DIR = os.path.join(_DATA_DIR, "tts_cache")

_EMPTY_STATE = {"cursors": {"vocab": 0, "grammar": 0, "phrase": 0}, "days_generated": {}}
_EMPTY_LIFESTYLE_STATE = {"read": {}}

_db = None
_gcs_bucket = None


def _client():
    global _db
    if _db is None:
        from google.cloud import firestore

        _db = firestore.Client()
    return _db


def _bucket():
    """Lazily-created GCS bucket handle for cached TTS audio. Audio blobs
    (tens-hundreds of KB each) don't belong in Firestore docs (1MB limit,
    and binary blobs eat into the 1GB/50K-ops free tier meant for the tiny
    text state); GCS's separate 5GB "Always Free" tier is the right place
    for them, mirroring how BJT-Wiki/lifestyle readings are static files
    rather than Firestore documents."""
    global _gcs_bucket
    if _gcs_bucket is None:
        from google.cloud import storage

        _gcs_bucket = storage.Client().bucket(_TTS_BUCKET)
    return _gcs_bucket


# ------------------------------------------------------------------ progress
def load_progress_state() -> dict:
    if _ON_CLOUD_RUN:
        doc = _client().collection(_PROGRESS_COLLECTION).document(_PROGRESS_DOC_ID).get()
        return doc.to_dict() if doc.exists else dict(_EMPTY_STATE)

    if os.path.exists(_PROGRESS_PATH):
        with open(_PROGRESS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return dict(_EMPTY_STATE)


def save_progress_state(state: dict) -> None:
    if _ON_CLOUD_RUN:
        _client().collection(_PROGRESS_COLLECTION).document(_PROGRESS_DOC_ID).set(state)
        return

    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_PROGRESS_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ------------------------------------------------------------------ passages
def save_passage(result: dict) -> str:
    passage_id = result["id"]
    if _ON_CLOUD_RUN:
        _client().collection(_PASSAGES_COLLECTION).document(passage_id).set(result)
        return passage_id

    os.makedirs(_PASSAGES_DIR, exist_ok=True)
    path = os.path.join(_PASSAGES_DIR, f"{passage_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return path


def load_passage(passage_id: str):
    if _ON_CLOUD_RUN:
        doc = _client().collection(_PASSAGES_COLLECTION).document(passage_id).get()
        return doc.to_dict() if doc.exists else None

    path = os.path.join(_PASSAGES_DIR, f"{passage_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def delete_passage(passage_id: str) -> bool:
    if _ON_CLOUD_RUN:
        ref = _client().collection(_PASSAGES_COLLECTION).document(passage_id)
        if ref.get().exists:
            ref.delete()
            return True
        return False

    path = os.path.join(_PASSAGES_DIR, f"{passage_id}.json")
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


def delete_all_passages() -> int:
    if _ON_CLOUD_RUN:
        docs = list(_client().collection(_PASSAGES_COLLECTION).stream())
        for doc in docs:
            doc.reference.delete()
        return len(docs)

    files = glob.glob(os.path.join(_PASSAGES_DIR, "*.json"))
    for path in files:
        os.remove(path)
    return len(files)



# --------------------------------------------------------------- lifestyle
def load_lifestyle_state() -> dict:
    """Which lifestyle readings the user has marked as read (small per-user
    doc, same pattern as the progress state)."""
    if _ON_CLOUD_RUN:
        doc = _client().collection(_PROGRESS_COLLECTION).document(_LIFESTYLE_STATE_DOC_ID).get()
        return doc.to_dict() if doc.exists else dict(_EMPTY_LIFESTYLE_STATE)

    if os.path.exists(_LIFESTYLE_STATE_PATH):
        with open(_LIFESTYLE_STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return dict(_EMPTY_LIFESTYLE_STATE)


def save_lifestyle_state(state: dict) -> None:
    if _ON_CLOUD_RUN:
        _client().collection(_PROGRESS_COLLECTION).document(_LIFESTYLE_STATE_DOC_ID).set(state)
        return

    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_LIFESTYLE_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def load_lifestyle_analysis(reading_id: str):
    """Cached AI-generated vocab/grammar glossary for one lifestyle reading,
    or None if it hasn't been generated yet (generated lazily, on first
    open, so only readings a user actually opens ever take up storage)."""
    if _ON_CLOUD_RUN:
        doc = _client().collection(_LIFESTYLE_ANALYSIS_COLLECTION).document(reading_id).get()
        return doc.to_dict() if doc.exists else None

    path = os.path.join(_LIFESTYLE_ANALYSIS_DIR, f"{reading_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_lifestyle_analysis(reading_id: str, data: dict) -> None:
    if _ON_CLOUD_RUN:
        _client().collection(_LIFESTYLE_ANALYSIS_COLLECTION).document(reading_id).set(data)
        return

    os.makedirs(_LIFESTYLE_ANALYSIS_DIR, exist_ok=True)
    path = os.path.join(_LIFESTYLE_ANALYSIS_DIR, f"{reading_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _touch_blob(blob) -> None:
    """Refresh a GCS object's `custom_time` to now, marking it as recently
    used. The bucket's lifecycle rule deletes objects whose custom_time
    hasn't been refreshed in 180+ days — this is what makes that an
    LRU-by-last-access eviction instead of a plain age-based one, without
    needing a cron job: audio nobody has listened to in 6 months gets
    reclaimed, audio still in regular use never does, no matter how old.
    Best-effort: a failed touch must never break serving the cached audio."""
    try:
        blob.custom_time = datetime.now(timezone.utc)
        blob.patch()
    except Exception:  # noqa: BLE001 - metadata refresh is non-critical
        pass


def load_tts_audio(cache_key: str):
    """Cached MP3 bytes for one reading/passage's audio narration, or None
    if it hasn't been synthesized yet (generated lazily on first listen)."""
    if _ON_CLOUD_RUN:
        blob = _bucket().blob(f"{cache_key}.mp3")
        if not blob.exists():
            return None
        audio_bytes = blob.download_as_bytes()
        _touch_blob(blob)
        return audio_bytes

    path = os.path.join(_TTS_CACHE_DIR, f"{cache_key}.mp3")
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return f.read()


def save_tts_audio(cache_key: str, audio_bytes: bytes) -> None:
    if _ON_CLOUD_RUN:
        blob = _bucket().blob(f"{cache_key}.mp3")
        blob.upload_from_string(audio_bytes, content_type="audio/mpeg")
        _touch_blob(blob)
        return

    os.makedirs(_TTS_CACHE_DIR, exist_ok=True)
    path = os.path.join(_TTS_CACHE_DIR, f"{cache_key}.mp3")
    with open(path, "wb") as f:
        f.write(audio_bytes)


def list_passages() -> list:
    """Newest-first list of full passage dicts (mirrors the old glob(reverse=True) order)."""
    if _ON_CLOUD_RUN:
        items = [d.to_dict() for d in _client().collection(_PASSAGES_COLLECTION).stream()]
        items.sort(key=lambda d: d.get("id", ""), reverse=True)
        return items

    files = sorted(glob.glob(os.path.join(_PASSAGES_DIR, "*.json")), reverse=True)
    items = []
    for path in files:
        with open(path, "r", encoding="utf-8") as f:
            items.append(json.load(f))
    return items
