# -*- coding: utf-8 -*-
"""BJT study web app: daily AI-generated reading passages + vocab lookup.

Run with: python -m bjt_app.app
Then open http://<your-lan-ip>:5000 from your phone (same Wi-Fi) or PC.
"""

import os
import sys
from datetime import date

if __package__ in (None, ""):
    # Allow `python app.py` / running from the IDE, not just `python -m bjt_app.app`.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

from bjt_app import ai_provider, storage
from bjt_app.furigana import add_furigana
from bjt_app.passage_generator import (
    LENGTH_PRESETS,
    LEVEL_LABELS,
    LEVEL_ORDER,
    DEFAULT_LENGTH,
    DEFAULT_LEVEL_BY_LENGTH,
    delete_all_passages,
    delete_passage,
    generate_passage,
    load_passage,
    save_passage,
)
from bjt_app.progress import clear_all_focus, delete_focus, get_daily_focus
from bjt_app.wiki_parser import parse_wiki

app = Flask(__name__)
app.jinja_env.filters["furigana"] = add_furigana

_VOCAB_CACHE = None


def _all_entries():
    global _VOCAB_CACHE
    if _VOCAB_CACHE is None:
        _VOCAB_CACHE = parse_wiki()
    return _VOCAB_CACHE


def _today() -> str:
    return date.today().isoformat()


def _valid_length(length: str) -> str:
    return length if length in LENGTH_PRESETS else DEFAULT_LENGTH


def _valid_level(level: str, length: str) -> str:
    if level in LEVEL_ORDER or level == "random":
        return level
    return DEFAULT_LEVEL_BY_LENGTH.get(length, "N2")


@app.route("/")
def index():
    length = _valid_length(request.args.get("length", DEFAULT_LENGTH))
    level = _valid_level(request.args.get("level"), length)
    return get_or_create_passage(_today(), length=length, level=level)


@app.route("/passage/<date_key>")
def get_or_create_passage(date_key: str, length: str = None, level: str = None):
    length = _valid_length(length or request.args.get("length", DEFAULT_LENGTH))
    level = _valid_level(level or request.args.get("level"), length)
    passage_id = f"{date_key}__{length}__{level}"

    passage = load_passage(passage_id)
    if passage is None:
        preset = LENGTH_PRESETS[length]
        focus = get_daily_focus(passage_id, batch_sizes=preset["batch_sizes"])
        passage = generate_passage(passage_id, focus, date_key, length=length, level=level)
        save_passage(passage)
    return render_template(
        "passage.html", p=passage, today=_today(), lengths=LENGTH_PRESETS, level_labels=LEVEL_LABELS
    )


@app.route("/passage/<date_key>/regenerate", methods=["POST"])
def regenerate_passage(date_key: str):
    length = _valid_length(request.args.get("length", DEFAULT_LENGTH))
    level = _valid_level(request.args.get("level"), length)
    passage_id = f"{date_key}__{length}__{level}"
    preset = LENGTH_PRESETS[length]

    focus = get_daily_focus(passage_id, batch_sizes=preset["batch_sizes"], force_new=True)
    passage = generate_passage(passage_id, focus, date_key, length=length, level=level)
    save_passage(passage)
    return jsonify({"ok": True, "redirect": f"/passage/{date_key}?length={length}&level={level}"})


@app.route("/history")
def history():
    items = [
        {
            "id": data.get("id", ""),
            "date": data["date"],
            "length": data.get("length", DEFAULT_LENGTH),
            "length_label": data.get("length_label", ""),
            "level": data.get("level", "N2"),
            "exam_level": data.get("exam_level", ""),
            "title": data.get("title", ""),
            "scenario": data.get("scenario", ""),
        }
        for data in storage.list_passages()
    ]
    return render_template("history.html", items=items)


@app.route("/history/<passage_id>/delete", methods=["POST"])
def delete_history_item(passage_id: str):
    deleted = delete_passage(passage_id)
    delete_focus(passage_id)
    return jsonify({"ok": True, "deleted": deleted})


@app.route("/history/delete-all", methods=["POST"])
def delete_history_all():
    count = delete_all_passages()
    clear_all_focus()
    return jsonify({"ok": True, "count": count})


@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        primary = request.form.get("primary_provider", "kaggle")
        order = [primary] + [p for p in ai_provider.PROVIDER_ORDER if p != primary]
        ai_provider.set_provider_priority(order)
        return redirect(url_for("settings"))

    order = ai_provider.get_provider_priority()
    return render_template("settings.html", order=order, primary=order[0] if order else "kaggle")


@app.route("/vocab")
def vocab():
    # Renders empty containers; JS fills them in from the browser's
    # localStorage of starred vocab/grammar items (client-side only,
    # nothing to look up server-side).
    return render_template("vocab.html")


@app.route("/api/vocab")
def api_vocab():
    q = request.args.get("q", "").strip().lower()
    entries = _all_entries()
    if q:
        entries = [
            e
            for e in entries
            if q in e["term"].lower() or q in e["reading"].lower() or q in e["meaning"].lower()
        ][:100]
    else:
        entries = entries[:60]
    return jsonify(entries)


if __name__ == "__main__":
    # PORT is set by Cloud Run at runtime; local dev keeps the old default 5013.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5013)), debug=not os.environ.get("K_SERVICE"))
