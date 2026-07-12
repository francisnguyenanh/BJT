# -*- coding: utf-8 -*-
"""Parse BJT-Wiki markdown tables into structured vocab/grammar/phrase entries.

The wiki uses plain pipe-tables with varying column names (Kanji, Từ, Mẫu,
Câu, Đọc, Nghĩa, Ví dụ, Cấu trúc, Ghi chú, ...). Rather than hard-coding one
schema per file, columns are classified by keyword so any table shape works.
"""

import os
import re

WIKI_ROOT_DEFAULT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "BJT-Wiki"
)

# Folders that hold learnable entries; README/overview files are skipped.
KIND_BY_FOLDER = {
    "01-Tu-Vung": "vocab",
    "02-Ngu-Phap": "grammar",
    "03-Phrase-Business": "phrase",
}

SKIP_FILES = {"README.md"}
SKIP_FOLDERS = {"00-Tong-Quan"}


def _classify_column(header: str) -> str:
    h = header.strip().lower()
    if "đọc" in h:
        return "reading"
    if "ví dụ" in h:
        return "example"
    if "cấu trúc" in h:
        return "structure"
    if "ghi chú" in h:
        return "note"
    if "mức độ" in h:
        return "level"
    if "mục đích" in h:
        return "note"
    if "nghĩa" in h:  # Nghĩa, Ý nghĩa, Nghĩa đen, Nghĩa bóng...
        return "meaning"
    return "extra"


def _split_row(line: str):
    cells = line.strip().strip("|").split("|")
    return [c.strip() for c in cells]


def _is_separator_row(cells) -> bool:
    return all(re.fullmatch(r":?-{2,}:?", c.strip()) for c in cells if c.strip())


def _parse_tables(text: str):
    """Yield (category, header_cells, rows) for every pipe-table in text,
    where category is the nearest preceding heading text."""
    lines = text.splitlines()
    category = None
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        heading = re.match(r"^#{1,3}\s+(.*)", line)
        if heading:
            category = heading.group(1).strip()
            i += 1
            continue
        if line.strip().startswith("|"):
            header_cells = _split_row(line)
            j = i + 1
            if j < n and _is_separator_row(_split_row(lines[j])):
                j += 1
                rows = []
                while j < n and lines[j].strip().startswith("|"):
                    row_cells = _split_row(lines[j])
                    rows.append(row_cells)
                    j += 1
                yield category, header_cells, rows
                i = j
                continue
        i += 1


def _infer_jlpt(filename: str):
    m = re.search(r"N[12]", filename, re.IGNORECASE)
    return m.group(0).upper() if m else None


def parse_file(path: str, kind: str):
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    source_file = os.path.basename(path)
    jlpt = _infer_jlpt(source_file)
    entries = []

    for category, header_cells, rows in _parse_tables(text):
        if len(header_cells) < 2:
            continue
        col_roles = [_classify_column(h) for h in header_cells]
        col_roles[0] = "term"  # first column is always the headword/phrase/pattern

        for row in rows:
            if len(row) != len(header_cells):
                continue
            if not row[0].strip() or row[0].strip() in {"", "-"}:
                continue

            entry = {
                "term": "",
                "reading": "",
                "meaning": "",
                "example": "",
                "structure": "",
                "note": "",
                "level": "",
            }
            meaning_parts = []
            for cell, role, header in zip(row, col_roles, header_cells):
                cell = cell.strip()
                if not cell:
                    continue
                if role == "term":
                    entry["term"] = cell
                elif role == "meaning":
                    if header.strip().lower() == "nghĩa":
                        meaning_parts.append(cell)
                    else:
                        meaning_parts.append(f"{header.strip()}: {cell}")
                elif role == "extra":
                    meaning_parts.append(f"{header.strip()}: {cell}")
                elif role in entry:
                    entry[role] = cell

            entry["meaning"] = "; ".join(meaning_parts)
            if not entry["term"] or not entry["meaning"]:
                continue

            entry["kind"] = kind
            entry["category"] = category or ""
            entry["jlpt"] = jlpt or ""
            entry["source_file"] = source_file
            entries.append(entry)

    return entries


def parse_wiki(wiki_root: str = WIKI_ROOT_DEFAULT):
    """Parse the whole wiki tree, returning entries in stable file/row order.

    Order follows the numeric filename prefixes (01, 02, ...) inside each
    folder, and folders are visited in the order vocab -> grammar -> phrase,
    matching the intended study progression.
    """
    all_entries = []
    order_index = 0

    for folder, kind in KIND_BY_FOLDER.items():
        folder_path = os.path.join(wiki_root, folder)
        if not os.path.isdir(folder_path):
            continue
        filenames = sorted(
            f
            for f in os.listdir(folder_path)
            if f.endswith(".md") and f not in SKIP_FILES
        )
        for filename in filenames:
            path = os.path.join(folder_path, filename)
            for entry in parse_file(path, kind):
                entry["order_index"] = order_index
                order_index += 1
                all_entries.append(entry)

    return all_entries


if __name__ == "__main__":
    entries = parse_wiki()
    by_kind = {}
    for e in entries:
        by_kind[e["kind"]] = by_kind.get(e["kind"], 0) + 1
    print(f"Total entries: {len(entries)}")
    for kind, count in by_kind.items():
        print(f"  {kind}: {count}")
    print("\nSample entries:")
    for e in entries[:3] + entries[len(entries) // 2 : len(entries) // 2 + 2]:
        print(f"  [{e['kind']}] {e['term']} | {e['reading']} | {e['meaning'][:50]}")
