# -*- coding: utf-8 -*-
"""Text-to-speech narration for readings, via Cloud Text-to-Speech (Chirp3-HD
Japanese voices) — not Vertex AI's Gemini audio-out, deliberately: Cloud TTS
has its own perpetual free tier (~1M characters/month for Chirp3-HD/Neural2/
WaveNet voices), while Gemini audio-out bills per token with no separate free
allowance. At this app's scale (2-3 readings/day, ~1.5-5K chars each) usage
stays a small fraction of that free tier.

Audio is generated lazily on first listen and cached (storage.py) keyed by
the reading/passage id, so the same text is never re-synthesized. The HTTP
response also sets a long-lived immutable Cache-Control header so the
browser/mobile OS caches the audio file itself after the first listen.
"""

import json
import re

from bjt_app import ai_provider, storage

LANGUAGE_CODE = "ja-JP"
# Chirp3-HD is Google's newest, most natural-sounding voice family (LLM-based,
# a step up from the older Neural2 synthesis) and shares the same 1M
# characters/month free-tier allowance as Neural2, so switching costs nothing.
DEFAULT_VOICE = "ja-JP-Chirp3-HD-Aoede"
VOICES = {
    "ja-JP-Chirp3-HD-Aoede": "Nữ (Chirp3-HD-Aoede)",
    "ja-JP-Chirp3-HD-Zephyr": "Nữ (Chirp3-HD-Zephyr)",
    "ja-JP-Chirp3-HD-Charon": "Nam (Chirp3-HD-Charon)",
    "ja-JP-Chirp3-HD-Fenrir": "Nam (Chirp3-HD-Fenrir)",
}

CONFIG_PATH_DEFAULT = ai_provider.CONFIG_PATH_DEFAULT

# Cloud TTS's synthesize_speech input cap is 5000 bytes; stay comfortably
# under that (Japanese chars are 3 bytes in UTF-8) and split on sentence
# boundaries so chunk edges don't fall mid-word.
_MAX_CHARS_PER_CALL = 1400
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？\n])")

# Chirp3-HD (unlike the older Neural2 voices) rejects a request outright if
# any single sentence is too long ("This request contains sentences that are
# too long"). Re-split oversized sentences on comma/pause boundaries so a
# long unbroken clause never reaches the API as one piece.
_MAX_CHARS_PER_SENTENCE = 200
_CLAUSE_SPLIT_RE = re.compile(r"(?<=[、,])")


def _split_long_sentence(sentence: str, max_chars: int) -> list:
    if len(sentence) <= max_chars:
        return [sentence]
    clauses = [c for c in _CLAUSE_SPLIT_RE.split(sentence) if c]
    pieces, current = [], ""
    for clause in clauses:
        if current and len(current) + len(clause) > max_chars:
            pieces.append(current)
            current = ""
        current += clause
    if current:
        pieces.append(current)
    return pieces or [sentence[:max_chars]]

_client = None


def _tts_client():
    global _client
    if _client is None:
        from google.cloud import texttospeech

        _client = texttospeech.TextToSpeechClient()
    return _client


def get_voice(config_path: str = CONFIG_PATH_DEFAULT) -> str:
    """User-configured narration voice (persisted alongside the AI provider
    priority in the same shared ai.config.json), defaulting to DEFAULT_VOICE."""
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    voice = config.get("tts_voice")
    return voice if voice in VOICES else DEFAULT_VOICE


def set_voice(voice: str, config_path: str = CONFIG_PATH_DEFAULT) -> None:
    if voice not in VOICES:
        raise ValueError(f"Unknown TTS voice: {voice}")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    config["tts_voice"] = voice
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def _split_into_chunks(text: str, max_chars: int = _MAX_CHARS_PER_CALL) -> list:
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(text) if s]
    sentences = [
        piece
        for sentence in sentences
        for piece in _split_long_sentence(sentence, _MAX_CHARS_PER_SENTENCE)
    ]
    chunks, current = [], ""
    for sentence in sentences:
        if current and len(current) + len(sentence) > max_chars:
            chunks.append(current)
            current = ""
        current += sentence
    if current:
        chunks.append(current)
    return chunks or [text]


def _synthesize_chunk(text: str, voice: str) -> bytes:
    from google.cloud import texttospeech

    client = _tts_client()
    response = client.synthesize_speech(
        input=texttospeech.SynthesisInput(text=text),
        voice=texttospeech.VoiceSelectionParams(
            language_code=LANGUAGE_CODE, name=voice
        ),
        audio_config=texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3
        ),
    )
    return response.audio_content


def synthesize(text: str, voice: str = None) -> bytes:
    """Synthesize `text` to MP3 bytes, chunking long passages (Cloud TTS
    caps a single request's input) and concatenating the resulting MP3
    frames back-to-back."""
    voice = voice or get_voice()
    return b"".join(_synthesize_chunk(chunk, voice) for chunk in _split_into_chunks(text))


def get_or_create_audio(kind: str, item_id: str, text: str) -> bytes:
    voice = get_voice()
    cache_key = f"{kind}__{item_id}__{voice}"
    cached = storage.load_tts_audio(cache_key)
    if cached is not None:
        return cached

    audio_bytes = synthesize(text, voice=voice)
    storage.save_tts_audio(cache_key, audio_bytes)
    return audio_bytes
