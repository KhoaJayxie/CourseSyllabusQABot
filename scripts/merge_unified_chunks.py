"""Refresh the unified dataset with added text chunks and context-sensitive tables."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
TEXT_PATH = DATA / "practical_nlp.text.chunks.jsonl"
CODE_PATH = DATA / "practical_nlp.code.chunks.jsonl"
TABLE_PATH = DATA / "practical_natural_language_processing.tables.json"
OUTPUT_PATH = DATA / "practical_nlp.unified.chunks.jsonl"
DOC_ID = "practical-natural-language-processing"


def jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as src:
        return [json.loads(line) for line in src if line.strip()]


def clean_embed_text(text: str) -> str:
    text = re.sub(r"(?<=\w)‐\s+(?=\w)", "", text)
    return re.sub(r"\s+", " ", text).strip()


def words(text: str) -> set[str]:
    return set(re.findall(r"[\w’'-]+", text.casefold()))


def table_anchor(table: dict[str, Any], text_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Find a same-page prose chunk containing the table's lead-in context."""
    context = str(table.get("context") or "")
    if not context:
        return None
    candidates = [r for r in text_rows if int(r["page_start"]) == int(table["page_start"])]
    if not candidates:
        return None
    # Longest context prefix avoids anchoring on common short words. Search
    # progressively shorter prefixes because PDF line-wrapping may split phrases.
    for length in (100, 80, 60, 45, 30):
        prefix = context[:length].strip()
        if len(prefix) < 20:
            continue
        match = next((r for r in candidates if prefix.casefold() in r["text"].casefold()), None)
        if match:
            return match
    # Fallback only when lexical overlap is meaningful and unique enough.
    context_words = words(context)
    scored = sorted(((len(context_words & words(r["text"])), r) for r in candidates), key=lambda item: item[0], reverse=True)
    if scored and scored[0][0] >= 5 and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        return scored[0][1]
    return None


def build() -> list[dict[str, Any]]:
    text_rows = jsonl(TEXT_PATH)
    code_rows = jsonl(CODE_PATH)
    table_rows = json.loads(TABLE_PATH.read_text(encoding="utf-8"))
    # Remove only text chunks whose provenance line ranges fall inside a
    # structured table's source page and whose text substantially matches its cells.
    table_cell_tokens: dict[int, list[set[str]]] = {}
    for table in table_rows:
        values = list(table.get("columns", []))
        for table_row in table.get("rows", []):
            values.extend(str(value) for value in table_row.values())
        table_cell_tokens.setdefault(int(table["page_start"]), []).append(words(" ".join(values)))
    deduped_text_rows: list[dict[str, Any]] = []
    removed_duplicate_ids: list[str] = []
    for row in text_rows:
        source_lines = [int(m.group(1)) for sid in row.get("source_line_ids", []) if (m := re.search(r":p\d+:l(\d+)$", sid))]
        duplicate = False
        for table in table_rows:
            page = int(table["page_start"])
            if int(row["page_start"]) != page or not source_lines:
                continue
            if not (min(source_lines) >= int(table.get("line_start", 1)) and max(source_lines) <= int(table.get("line_end", 10**9))):
                continue
            text_words = words(row["text"])
            for cell_words in table_cell_tokens.get(page, []):
                if len(text_words) >= 20 and len(text_words & cell_words) / len(text_words) >= 0.85:
                    duplicate = True
                    break
            if duplicate:
                break
        if duplicate:
            removed_duplicate_ids.append(row["chunk_id"])
        else:
            deduped_text_rows.append(row)
    text_rows = deduped_text_rows
    records: list[dict[str, Any]] = []

    for row in text_rows:
        ctype, text = row["type"], row["text"]
        if ctype not in {"text", "toc"}:
            raise ValueError(f"Unexpected text type: {ctype}")
        local_order = int(re.search(r"(\d+)$", row["chunk_id"]).group(1))
        records.append({
            "chunk_id": row["chunk_id"], "document_id": DOC_ID, "chunk_type": ctype, "subtype": None,
            "_local_order": local_order, "_tie": 0,
            "page_start": int(row["page_start"]), "page_end": int(row["page_end"]), "page_inferred": False,
            "embed_text": "" if ctype == "toc" else clean_embed_text(text),
            "content": {"text": text},
            "relations": {"parent_id": None, "related_table_ids": [], "depends_on": [], "step": None, "prev_id": None, "next_id": None},
            "provenance": {"source_line_ids": row.get("source_line_ids", []), "line_start": row.get("line_start"), "line_end": row.get("line_end")},
            "quality": {"status": "ok", "review_reasons": [], "notes": []}, "lang": "en",
        })

    for row in code_rows:
        pages = row["page"] if isinstance(row["page"], list) else [row["page"]]
        starts = row["start_line"] if isinstance(row["start_line"], list) else [row["start_line"]]
        ends = row["end_line"] if isinstance(row["end_line"], list) else [row["end_line"]]
        if len(starts) == 1 and len(pages) > 1:
            starts = [starts[0], starts[0]]
        if len(ends) == 1 and len(pages) > 1:
            ends = [ends[0], ends[0]]
        if len(pages) != len(starts) or len(pages) != len(ends):
            raise ValueError(f"Code page/line range lengths mismatch for {row['id']}")
        symbol, code, description = row["symbol"], row["text"], row["description"]
        records.append({
            "chunk_id": f"{DOC_ID}:code:{symbol}", "document_id": DOC_ID, "chunk_type": "code", "subtype": row["chunk_type"],
            "_local_order": int(row["step"]), "_tie": 0,
            "page_start": int(pages[0]), "page_end": int(pages[-1]), "page_inferred": False,
            "embed_text": f"{description}\n{symbol}\n{code}",
            "content": {"code": code, "language": row["language"], "symbol": symbol, "description": description, "description_lang": "vi"},
            "relations": {"parent_id": None, "related_table_ids": [], "depends_on": row.get("depends_on", []), "step": row.get("step"), "prev_id": None, "next_id": None},
            "provenance": {"source_line_ids": [], "line_start": min(map(int, starts)), "line_end": max(map(int, ends))},
            "quality": {"status": "ok", "review_reasons": [], "notes": []}, "lang": "code",
        })

    for index, row in enumerate(table_rows):
        caption, context = row.get("caption"), row.get("context")
        anchor = table_anchor(row, text_rows)
        local_order = int(re.search(r"(\d+)$", anchor["chunk_id"]).group(1)) if anchor else index
        table_text = row.get("text") or "\n".join(filter(None, [caption, context]))
        records.append({
            "chunk_id": row["chunk_id"], "document_id": DOC_ID, "chunk_type": "table", "subtype": None,
            "_local_order": local_order, "_tie": 1,
            "page_start": int(row["page_start"]), "page_end": int(row["page_end"]), "page_inferred": bool(row.get("page_inferred", False)),
            "embed_text": table_text,
            "content": {"table_id": row.get("table_id"), "caption": caption, "columns": row.get("columns", []), "header_type": row.get("header_type"), "rows": row.get("rows", []), "context": context, "unit": row.get("unit")},
            "relations": {"parent_id": row.get("parent_id"), "related_table_ids": row.get("related_table_ids", []), "depends_on": [], "step": None, "prev_id": None, "next_id": None},
            "provenance": {"source_line_ids": row.get("source_line_ids", []), "line_start": None, "line_end": None},
            "quality": {"status": row.get("status", "ok"), "review_reasons": row.get("review_reasons", []), "notes": row.get("notes", [])}, "lang": "en",
        })

    records.sort(key=lambda r: (r["page_start"], r["_local_order"], r.get("_tie", 0), {"text": 0, "toc": 1, "table": 2, "code": 3}[r["chunk_type"]], r["chunk_id"]))
    for i, row in enumerate(records):
        row["order"] = i
        row.pop("_local_order", None)
        row.pop("_tie", None)
    by_type: dict[str, list[dict[str, Any]]] = {}
    for row in records:
        by_type.setdefault(row["chunk_type"], []).append(row)
    for typed in by_type.values():
        for i, row in enumerate(typed):
            row["relations"]["prev_id"] = typed[i - 1]["chunk_id"] if i else None
            row["relations"]["next_id"] = typed[i + 1]["chunk_id"] if i + 1 < len(typed) else None
    return records


def validate(records: list[dict[str, Any]]) -> None:
    text_rows, code_rows = jsonl(TEXT_PATH), jsonl(CODE_PATH)
    table_rows = json.loads(TABLE_PATH.read_text(encoding="utf-8"))
    expected = len(text_rows) + len(code_rows) + len(table_rows)
    # Validate text-source preservation except chunks intentionally removed because
    # their extracted lines are the same table cells represented structurally.
    table_cell_tokens: dict[int, list[set[str]]] = {}
    for table in table_rows:
        values = list(table.get("columns", []))
        for table_row in table.get("rows", []):
            values.extend(str(value) for value in table_row.values())
        table_cell_tokens.setdefault(int(table["page_start"]), []).append(words(" ".join(values)))
    expected_text_ids = set()
    for source in text_rows:
        line_numbers = [int(m.group(1)) for sid in source.get("source_line_ids", []) if (m := re.search(r":p\d+:l(\d+)$", sid))]
        duplicate = False
        for table in table_rows:
            page = int(table["page_start"])
            if int(source["page_start"]) != page or not line_numbers:
                continue
            if not (min(line_numbers) >= int(table.get("line_start", 1)) and max(line_numbers) <= int(table.get("line_end", 10**9))):
                continue
            token_set = words(source["text"])
            if any(len(token_set) >= 20 and len(token_set & cells) / len(token_set) >= 0.85 for cells in table_cell_tokens.get(page, [])):
                duplicate = True
                break
        if not duplicate:
            expected_text_ids.add(source["chunk_id"])
    expected -= len(text_rows) - len(expected_text_ids)
    if len(records) != expected:
        raise ValueError(f"Expected {expected} records, got {len(records)}")
    ids = [r["chunk_id"] for r in records]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate chunk_id detected")
    if {r["document_id"] for r in records} != {DOC_ID}:
        raise ValueError("Inconsistent document_id")
    forbidden = {"id", "file", "type", "page", "start_line", "end_line"}
    for row in records:
        if forbidden.intersection(row):
            raise ValueError(f"Legacy top-level field found in {row['chunk_id']}")
        if not isinstance(row["page_start"], int) or not isinstance(row["page_end"], int) or row["page_start"] > row["page_end"]:
            raise ValueError(f"Invalid page range in {row['chunk_id']}")
    table_out = {r["chunk_id"]: r for r in records if r["chunk_type"] == "table"}
    for source in table_rows:
        target = table_out[source["chunk_id"]]
        if target["content"]["columns"] != source["columns"] or target["content"]["rows"] != source["rows"]:
            raise ValueError(f"Table content changed: {source['chunk_id']}")
        if target["quality"]["status"] != source["status"]:
            raise ValueError(f"Table quality changed: {source['chunk_id']}")
    code_src = {r["symbol"]: r for r in code_rows}
    text_src = {r["chunk_id"]: r for r in text_rows}
    for row in records:
        if row["chunk_type"] == "code" and row["content"]["code"] != code_src[row["content"]["symbol"]]["text"]:
            raise ValueError(f"Code content changed: {row['chunk_id']}")
        if row["chunk_type"] in {"text", "toc"} and row["content"]["text"] != text_src[row["chunk_id"]]["text"]:
            raise ValueError(f"Text content changed: {row['chunk_id']}")
    if sum(r["quality"]["status"] == "needs_review" for r in table_out.values()) != 8:
        raise ValueError("Expected 8 table chunks with needs_review")


def main() -> None:
    sys.stdout.reconfigure(errors="backslashreplace")
    records = build()
    validate(records)
    with OUTPUT_PATH.open("w", encoding="utf-8", newline="\n") as out:
        for row in records:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Wrote {len(records)} chunks to {OUTPUT_PATH}")
    print("Validation passed: source content preserved; IDs unique; table review statuses preserved.")


if __name__ == "__main__":
    main()
