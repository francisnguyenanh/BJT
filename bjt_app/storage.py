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

_ON_CLOUD_RUN = bool(os.getenv("K_SERVICE"))

_PROGRESS_COLLECTION = "bjt_state"
_PROGRESS_DOC_ID = "progress"
_PASSAGES_COLLECTION = "bjt_passages"

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_PROGRESS_PATH = os.path.join(_DATA_DIR, "progress.json")
_PASSAGES_DIR = os.path.join(_DATA_DIR, "passages")

_EMPTY_STATE = {"cursors": {"vocab": 0, "grammar": 0, "phrase": 0}, "days_generated": {}}

_db = None


def _client():
    global _db
    if _db is None:
        from google.cloud import firestore

        _db = firestore.Client()
    return _db


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
