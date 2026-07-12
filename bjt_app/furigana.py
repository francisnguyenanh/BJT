# -*- coding: utf-8 -*-
"""Auto-generate furigana (ruby annotations) for Japanese text using fugashi
(MeCab + unidic), so passages don't depend on the AI reliably emitting
correct reading markup.

Renders straight to escaped HTML with <ruby><rt> tags; mark the result
`| safe` in Jinja templates.
"""

import html
import re

_tagger = None

_KANJI_RE = re.compile(r"[㐀-鿿々豈-﫿]")
_HIRAGANA_RANGE = ("ぁ", "ゟ")


def _get_tagger():
    global _tagger
    if _tagger is None:
        import fugashi

        _tagger = fugashi.Tagger()
    return _tagger


def _kata_to_hira(s: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)


def _has_kanji(s: str) -> bool:
    return bool(_KANJI_RE.search(s))


def _is_hiragana(c: str) -> bool:
    return _HIRAGANA_RANGE[0] <= c <= _HIRAGANA_RANGE[1]


def _ruby_for_token(surface: str, reading: str) -> str:
    if not reading or reading == surface or not _has_kanji(surface):
        return html.escape(surface)

    start, end = 0, len(surface)
    r_start, r_end = 0, len(reading)

    # Strip matching okurigana (hiragana that appears identically in both
    # the surface form and its reading) from the tail, then the head, so
    # only the kanji core gets a ruby annotation.
    while (
        end > start
        and r_end > r_start
        and surface[end - 1] == reading[r_end - 1]
        and _is_hiragana(surface[end - 1])
    ):
        end -= 1
        r_end -= 1
    while (
        start < end
        and r_start < r_end
        and surface[start] == reading[r_start]
        and _is_hiragana(surface[start])
    ):
        start += 1
        r_start += 1

    prefix, core, suffix = surface[:start], surface[start:end], surface[end:]
    core_reading = reading[r_start:r_end]

    if not core or not _has_kanji(core) or not core_reading or core_reading == core:
        return html.escape(surface)

    return (
        html.escape(prefix)
        + f"<ruby>{html.escape(core)}<rt>{html.escape(core_reading)}</rt></ruby>"
        + html.escape(suffix)
    )


def add_furigana(text: str) -> str:
    """Return `text` as HTML with <ruby> furigana over kanji. Safe to mark
    `| safe` in Jinja: all non-kanji text is HTML-escaped."""
    if not text:
        return ""

    tagger = _get_tagger()
    parts = []
    for word in tagger(text):
        surface = word.surface
        kana = getattr(word.feature, "kana", None) or getattr(word.feature, "pron", None) or ""
        reading = _kata_to_hira(kana)
        parts.append(_ruby_for_token(surface, reading))
    return "".join(parts)


if __name__ == "__main__":
    import sys

    sample = sys.argv[1] if len(sys.argv) > 1 else "本日は臨時休業につき、ご迷惑をおかけします。"
    sys.stdout.buffer.write((add_furigana(sample) + "\n").encode("utf-8"))
