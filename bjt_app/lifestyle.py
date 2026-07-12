# -*- coding: utf-8 -*-
"""Life Style reading passages: a fixed pool of pre-written Japanese texts
(baked into the image as static JSON, not stored in Firestore — they never
change at runtime). Furigana is rendered on the fly via the existing MeCab
filter. Vocab/grammar glossaries are AI-generated lazily, the first time a
user opens a given reading, and cached from then on (storage.py), so AI
calls and stored analysis only ever cover the readings someone actually
opens instead of all ~2700 up front."""

import json
import os
import re

from bjt_app import ai_provider, storage

_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lifestyle_data", "readings.json")

_READINGS = None
_READINGS_BY_ID = None


def _load():
    global _READINGS, _READINGS_BY_ID
    if _READINGS is None:
        with open(_DATA_PATH, "r", encoding="utf-8") as f:
            _READINGS = json.load(f)
        _READINGS_BY_ID = {r["id"]: r for r in _READINGS}
    return _READINGS


def list_readings() -> list:
    """All readings in file order, each as {id, title}."""
    return [{"id": r["id"], "title": r["title"]} for r in _load()]


def get_reading(reading_id: str):
    _load()
    return _READINGS_BY_ID.get(reading_id)


def list_with_read_state() -> tuple:
    """Split all readings into (unread, read) lists, each item {id, title},
    ordered read-most-recent-first within the "read" section."""
    state = storage.load_lifestyle_state()
    read_map = state.get("read", {})

    unread, read = [], []
    for r in _load():
        item = {"id": r["id"], "title": r["title"]}
        if r["id"] in read_map:
            item["read_at"] = read_map[r["id"]]
            read.append(item)
        else:
            unread.append(item)
    read.sort(key=lambda it: it["read_at"], reverse=True)
    return unread, read


def is_read(reading_id: str) -> bool:
    state = storage.load_lifestyle_state()
    return reading_id in state.get("read", {})


def set_read(reading_id: str, read: bool, timestamp: str) -> None:
    state = storage.load_lifestyle_state()
    read_map = state.setdefault("read", {})
    if read:
        read_map[reading_id] = timestamp
    else:
        read_map.pop(reading_id, None)
    storage.save_lifestyle_state(state)


def _build_analysis_prompt(text: str) -> str:
    return f"""Bạn là giáo viên tiếng Nhật. Dưới đây là một đoạn văn tiếng Nhật (bài đọc đời sống/self-help):

{text}

Hãy đọc kỹ đoạn văn trên và trích xuất:
- "vocab_glossary": TẤT CẢ từ vựng (danh từ, động từ, tính từ, phó từ, thành ngữ...) THỰC SỰ xuất hiện
  trong đoạn văn có cấp độ N3 hoặc cao hơn (N3/N2/N1), kèm cách đọc hiragana và nghĩa tiếng Việt ngắn gọn.
  Bỏ qua trợ từ và từ vựng N5/N4 quá cơ bản (これ、あります、する...). Không bỏ sót từ nào ở mức N3+
  thực sự có trong bài.
- "grammar_glossary": TẤT CẢ mẫu ngữ pháp N2, N1 THỰC SỰ xuất hiện trong đoạn văn (bỏ qua ngữ pháp
  N5/N4 cơ bản), kèm cấu trúc ngắn gọn, nghĩa tiếng Việt, và câu ví dụ phải là CÂU TRÍCH NGUYÊN VĂN
  từ chính đoạn văn có chứa mẫu ngữ pháp đó (không tự đặt câu mới).

TRẢ VỀ DUY NHẤT một JSON hợp lệ (không markdown, không giải thích thêm) theo đúng schema:
{{
  "vocab_glossary": [
    {{"term": "từ tiếng Nhật", "reading": "cách đọc hiragana", "meaning": "nghĩa tiếng Việt", "level": "N3|N2|N1"}}
  ],
  "grammar_glossary": [
    {{"pattern": "mẫu ngữ pháp", "structure": "cấu trúc ngắn gọn", "meaning": "nghĩa tiếng Việt", "example": "câu trích nguyên văn", "level": "N2|N1"}}
  ]
}}
"""


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in model output: {text[:300]}")
    return json.loads(text[start : end + 1])


def get_or_create_analysis(reading_id: str) -> dict:
    cached = storage.load_lifestyle_analysis(reading_id)
    if cached is not None:
        return cached

    reading = get_reading(reading_id)
    if reading is None:
        raise ValueError(f"Unknown lifestyle reading id: {reading_id}")

    prompt = _build_analysis_prompt(reading["text"])
    raw, provider_used = ai_provider.ask(prompt)
    parsed = _extract_json(raw)

    analysis = {
        "id": reading_id,
        "provider": provider_used,
        "vocab_glossary": parsed.get("vocab_glossary", []),
        "grammar_glossary": parsed.get("grammar_glossary", []),
    }
    storage.save_lifestyle_analysis(reading_id, analysis)
    return analysis
