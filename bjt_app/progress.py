# -*- coding: utf-8 -*-
"""Track daily rotation through the wiki so each day's reading passage
focuses on a fresh, non-repeating batch of vocab/grammar/phrases until the
whole wiki has been cycled through, then it loops back to the start."""

from bjt_app import storage
from bjt_app.wiki_parser import parse_wiki

BATCH_SIZES = {"vocab": 12, "grammar": 2, "phrase": 2}


def _group_by_kind(entries):
    grouped = {"vocab": [], "grammar": [], "phrase": []}
    for e in entries:
        grouped.setdefault(e["kind"], []).append(e)
    return grouped


def _take_batch(items, cursor, size):
    if not items:
        return [], cursor
    n = len(items)
    size = min(size, n)
    batch = [items[(cursor + i) % n] for i in range(size)]
    return batch, (cursor + size) % n


def get_daily_focus(
    date_key: str,
    wiki_root=None,
    force_new: bool = False,
    batch_sizes: dict = None,
):
    """Return this cache key's focus entries {vocab: [...], grammar: [...], phrase: [...]}.

    Calling again with the same date_key returns the same batch (idempotent)
    unless force_new=True, so refreshing a page never silently reshuffles
    the material you're mid-way through studying. date_key can be any stable
    cache id (e.g. "2026-07-09__long") — callers decide what varies the batch.
    """
    state = storage.load_progress_state()
    cached = state.get("days_generated", {}).get(date_key)
    if cached and not force_new:
        return cached

    entries = parse_wiki(wiki_root) if wiki_root else parse_wiki()
    grouped = _group_by_kind(entries)
    sizes = batch_sizes or BATCH_SIZES

    focus = {}
    cursors = state.setdefault("cursors", {"vocab": 0, "grammar": 0, "phrase": 0})
    for kind, size in sizes.items():
        batch, new_cursor = _take_batch(grouped.get(kind, []), cursors.get(kind, 0), size)
        cursors[kind] = new_cursor
        focus[kind] = batch

    state.setdefault("days_generated", {})[date_key] = focus
    storage.save_progress_state(state)
    return focus


def delete_focus(date_key: str) -> bool:
    """Drop one cached day's focus batch (does not touch the rotation
    cursors, so vocab rotation keeps advancing from where it left off)."""
    state = storage.load_progress_state()
    removed = state.get("days_generated", {}).pop(date_key, None)
    storage.save_progress_state(state)
    return removed is not None


def clear_all_focus() -> None:
    state = storage.load_progress_state()
    state["days_generated"] = {}
    storage.save_progress_state(state)


if __name__ == "__main__":
    import sys

    date_key = sys.argv[1] if len(sys.argv) > 1 else "test-day"
    focus = get_daily_focus(date_key)
    for kind, items in focus.items():
        print(f"{kind}: {[i['term'] for i in items]}")
