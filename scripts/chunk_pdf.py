"""Create reviewable text chunks while preserving page/line source mappings."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from syllabus_qa.ingest.chunker import make_chunks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-chars", type=int, default=1800)
    parser.add_argument("--target-chars", type=int, default=1000)
    args = parser.parse_args()

    with args.input.open(encoding="utf-8") as source:
        rows = [json.loads(line) for line in source if line.strip()]
    chunks = make_chunks(rows, args.max_chars, args.target_chars)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as output:
        for chunk in chunks:
            output.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    too_long = sum(len(chunk["text"]) > args.max_chars for chunk in chunks)
    table_flags = sum("table_like" in chunk["review_flags"] for chunk in chunks)
    print(f"Input lines: {len(rows)}")
    print(f"Chunks: {len(chunks)}")
    print(f"Chunks over max chars ({args.max_chars}): {too_long}")
    print(f"Chunks flagged table-like (review hint only): {table_flags}")
    print(f"Output: {args.output}")


if __name__ == "__main__":
    main()
