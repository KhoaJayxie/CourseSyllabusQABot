"""Create text-only chunks from the book's extracted page lines for review."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
INPUT = DATA / "book.lines.jsonl"
CODE = DATA / "practical_nlp.code.chunks.jsonl"
OUTPUT = DATA / "practical_nlp.text.chunks.jsonl"

FIGURE_CAPTION = re.compile(r"^Figure\s+\d+(?:-\d+)?\.\s+", re.I)
TABLE_CAPTION = re.compile(r"^Table\s+\d+(?:-\d+)?\.\s+", re.I)
REF_HEADING = re.compile(r"^(?:References|Bibliography)\s*$", re.I)
HEADER_FOOTER = re.compile(r"^(?:\d+\s*\|\s*Chapter\s+\d+.*|Chapter\s+\d+.*\|\s*\d+|\d+\s*\|\s*.+|.+\s\|\s*\d+)$", re.I)
CODE_CUES = re.compile(r"^(?:>>>|\.\.\.|#!|import\s+|from\s+\S+\s+import\s+|def\s+\w+\s*\(|class\s+\w+\b|\s{4,}(?:return|if|for|while|print|self\.|\w+\s*=))")


def render(lines: list[str]) -> str:
    out = ""
    for line in lines:
        value = line.strip()
        if not value:
            continue
        if not out:
            out = value
        elif out.endswith("-") and value[:1].islower():
            out = out[:-1] + value
        else:
            out += " " + value
    return out


def sentence_end(text: str) -> bool:
    return bool(re.search(r"[.!?][\"'”’)]*$", text.strip()))


def main() -> None:
    rows = [json.loads(line) for line in INPUT.open(encoding="utf-8") if line.strip()]
    code_ranges: dict[int, list[tuple[int, int]]] = {}
    for raw in CODE.open(encoding="utf-8"):
        if not raw.strip():
            continue
        c = json.loads(raw)
        pages = c["page"] if isinstance(c["page"], list) else [c["page"]]
        starts = c.get("start_line", [])
        ends = c.get("end_line", [])
        if not isinstance(starts, list):
            starts = [starts]
        if not isinstance(ends, list):
            ends = [ends]
        if len(starts) == 1 and len(pages) > 1:
            starts = [starts[0], starts[0]]
        if len(ends) == 1 and len(pages) > 1:
            ends = [ends[0], ends[0]]
        for page, start, end in zip(pages, starts, ends):
            page = int(page)
            start = int(start)
            end = int(end)
            # Multi-page snippets use the first page's start and final page's end.
            code_ranges.setdefault(page, []).append((start, end) if start <= end else (1, 10**9))

    kept: list[dict] = []
    in_references = False
    page_lines: dict[int, list[dict]] = {}
    for row in rows:
        page_lines.setdefault(int(row["page"]), []).append(row)
    for page in sorted(page_lines):
        page_rows = page_lines[page]
        for row in page_rows:
            text = str(row["text"]).strip()
            if re.match(r"^\d+\.\s+\S", text) or re.match(r"^Index(?:\.|\s|$)", text, re.I):
                in_references = False
            if REF_HEADING.match(text):
                in_references = True
            if in_references:
                continue
            line = int(row["line"])
            if any(start <= line <= end for start, end in code_ranges.get(page, [])):
                continue
            if not text or HEADER_FOOTER.match(text) or FIGURE_CAPTION.match(text) or TABLE_CAPTION.match(text):
                continue
            # Drop TOC entries, which are not explanatory prose.
            if 9 <= page <= 15 or text.casefold() == "table of contents":
                continue
            # Drop rows that are clearly code, but avoid discarding prose mentioning code terms.
            if CODE_CUES.match(text):
                continue
            kept.append(row)

    # Build contiguous page-local prose groups; split only after a complete sentence.
    chunks: list[dict] = []
    current: list[dict] = []
    for row in kept:
        if current and (int(row["page"]) != int(current[-1]["page"]) or int(row["line"]) != int(current[-1]["line"]) + 1):
            # If a removed line was a caption/table/code, retain the paragraph's remaining prose,
            # but begin a fresh chunk to avoid joining across excluded material.
            text = render([r["text"] for r in current])
            if text:
                chunks.append((current, text))
            current = []
        current.append(row)
        candidate = render([r["text"] for r in current])
        if len(candidate) >= 1300 and sentence_end(candidate):
            chunks.append((current, candidate))
            current = []
    if current:
        text = render([r["text"] for r in current])
        if text:
            chunks.append((current, text))

    with OUTPUT.open("w", encoding="utf-8", newline="\n") as out:
        for index, (group, text) in enumerate(chunks, start=1):
            first, last = group[0], group[-1]
            record = {
                "chunk_id": f"practical-natural-language-processing:text:{index:04d}",
                "document_id": first["document_id"],
                "type": "toc" if int(first["page"]) <= 15 else "text",
                "text": text,
                "page_start": int(first["page"]),
                "page_end": int(last["page"]),
                "line_start": int(first["line"]),
                "line_end": int(last["line"]),
                "source_line_ids": [f"{first['document_id']}:p{r['page']}:l{r['line']}" for r in group],
            }
            out.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"Input lines: {len(rows)}")
    print(f"Text chunks: {len(chunks)}")
    print(f"Output: {OUTPUT}")

if __name__ == "__main__":
    main()
