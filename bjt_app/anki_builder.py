# -*- coding: utf-8 -*-
"""Build an Anki (.apkg) deck from the parsed BJT wiki entries."""

import hashlib
import os

import genanki

from bjt_app.wiki_parser import parse_wiki

OUTPUT_DEFAULT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "BJT_Anki_Deck.apkg"
)

KIND_LABEL = {"vocab": "Tu vung", "grammar": "Ngu phap", "phrase": "Phrase Business"}


def _stable_id(*parts: str) -> int:
    digest = hashlib.sha1("::".join(parts).encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


def _deck_id(deck_name: str) -> int:
    # genanki deck ids must fit a positive 32-bit-ish range; reuse stable hash.
    return _stable_id("deck", deck_name) % 1_000_000_000 + 1_000_000_000


MODEL = genanki.Model(
    _stable_id("model", "bjt-basic") % 1_000_000_000 + 1_000_000_000,
    "BJT Basic",
    fields=[
        {"name": "Term"},
        {"name": "Reading"},
        {"name": "Meaning"},
        {"name": "Example"},
        {"name": "Note"},
        {"name": "Category"},
        {"name": "Source"},
    ],
    templates=[
        {
            "name": "Recognition",
            "qfmt": (
                "<div class='term'>{{Term}}</div>"
                "{{#Example}}<div class='example'>{{Example}}</div>{{/Example}}"
            ),
            "afmt": (
                "{{FrontSide}}<hr>"
                "{{#Reading}}<div class='reading'>{{Reading}}</div>{{/Reading}}"
                "<div class='meaning'>{{Meaning}}</div>"
                "{{#Note}}<div class='note'>{{Note}}</div>{{/Note}}"
                "<div class='source'>{{Category}} &middot; {{Source}}</div>"
            ),
        }
    ],
    css=(
        ".card { font-family: 'Yu Gothic', 'Meiryo', sans-serif; font-size: 20px; "
        "text-align: center; color: #222; background: #fff; }\n"
        ".term { font-size: 32px; font-weight: bold; }\n"
        ".example { font-size: 18px; color: #555; margin-top: 8px; }\n"
        ".reading { font-size: 20px; color: #0a6; margin-top: 6px; }\n"
        ".meaning { font-size: 22px; margin-top: 6px; }\n"
        ".note { font-size: 15px; color: #777; margin-top: 6px; }\n"
        ".source { font-size: 12px; color: #aaa; margin-top: 10px; }\n"
    ),
)


def build_deck(wiki_root=None, output_path: str = OUTPUT_DEFAULT):
    entries = parse_wiki(wiki_root) if wiki_root else parse_wiki()

    decks_by_name = {}
    for e in entries:
        kind_label = KIND_LABEL.get(e["kind"], e["kind"])
        deck_name = f"BJT::{kind_label}::{e['source_file'].replace('.md', '')}"
        if deck_name not in decks_by_name:
            decks_by_name[deck_name] = genanki.Deck(_deck_id(deck_name), deck_name)

        note = genanki.Note(
            model=MODEL,
            fields=[
                e["term"],
                e["reading"],
                e["meaning"],
                e["example"],
                e["note"],
                e["category"],
                e["source_file"],
            ],
            guid=genanki.guid_for(e["source_file"], e["term"], e["category"]),
        )
        decks_by_name[deck_name].add_note(note)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    genanki.Package(list(decks_by_name.values())).write_to_file(output_path)
    return output_path, len(entries), len(decks_by_name)


if __name__ == "__main__":
    path, count, deck_count = build_deck()
    print(f"Wrote {count} cards across {deck_count} decks to {path}")
