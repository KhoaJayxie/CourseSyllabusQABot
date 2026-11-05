"""Verify chunk provenance, size limits, footers, and table boundaries."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def is_running_footer(text: str) -> bool:
    value = text.strip()
    if re.match(r"^\d+\s*\|\s*Chapter\s+\d+\s*:", value, re.IGNORECASE):
        return True
    match = re.match(r"^(\d+)\s*\|\s*Chapter\s+(\d+)\s+(.+)$", value, re.IGNORECASE)
    if match:
        printed_page, chapter, title = match.groups()
        return int(printed_page) != int(chapter) and "table" not in title.casefold()
    return value.count("|") == 1 and bool(re.match(r"^.+\s\|\s\d+$", value))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("chunks", type=Path)
    parser.add_argument("--max-chars", type=int, default=1800)
    args = parser.parse_args()
    source = read_jsonl(args.source)
    chunks = read_jsonl(args.chunks)
    expected = Counter(
        (r["document_id"], int(r["page"]), int(r["line"]))
        for r in source if not is_running_footer(r["text"])
    )
    actual = Counter(
        (c["document_id"], int(s["page"]), int(s["line"]))
        for c in chunks for s in c["source_lines"]
    )
    errors: list[str] = []
    if expected != actual:
        errors.append(
            f"provenance mismatch: missing={sum((expected-actual).values())}, "
            f"unexpected/duplicate={sum((actual-expected).values())}"
        )

    too_long = [c["chunk_id"] for c in chunks if len(c["text"]) > args.max_chars]
    empty = [c["chunk_id"] for c in chunks if not c["text"].strip()]
    if too_long:
        errors.append(f"{len(too_long)} chunks exceed {args.max_chars} characters")
    if empty:
        errors.append(f"{len(empty)} chunks have empty text")

    source_text = {(r["document_id"], int(r["page"]), int(r["line"])): r["source_text"] for r in source}
    for chunk in chunks:
        for line in chunk["source_lines"]:
            key = (chunk["document_id"], int(line["page"]), int(line["line"]))
            if line["text"] != source_text.get(key):
                errors.append(f"source text changed for {key}")
                break

    samples: list[str] = []
    for page in (9, 17, 99, 100):
        page_chunks = [c for c in chunks if int(c["page_start"]) == page]
        samples.extend(f"page {page} L{c['line_start']}-{c['line_end']}: {c['text'][:250]}" for c in page_chunks[:4])

    metric_chunks = [c for c in chunks if int(c["page_start"]) == 100]
    if any("table_layout_review" not in c["review_flags"] for c in metric_chunks if c["line_start"] <= 15):
        errors.append("table content on page 100 is missing review flag")
    table_tail = [c for c in metric_chunks if c["line_start"] >= 16]
    if any("table_layout_review" in c["review_flags"] for c in table_tail):
        errors.append("prose after metric table on page 100 is incorrectly flagged as table")
    if any("Apart from the list of metrics" in c["text"] and "ROUGE" in c["text"] for c in metric_chunks):
        errors.append("paragraph after table is merged into ROUGE table chunk")

    print(f"Source lines: {len(source)}")
    print(f"Expected lines after footer filtering: {sum(expected.values())}")
    print(f"Chunks: {len(chunks)}")
    print(f"Provenance missing/extra/duplicate: {sum((expected-actual).values())}/{sum((actual-expected).values())}")
    print(f"Chunks over max: {len(too_long)}")
    print(f"Empty chunks: {len(empty)}")
    for sample in samples:
        print(f"SAMPLE {sample.encode('ascii', 'replace').decode('ascii')}")
    if errors:
        for error in errors[:10]:
            print(f"ERROR: {error}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
