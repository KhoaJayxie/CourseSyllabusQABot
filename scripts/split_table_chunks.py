"""Split approved table chunks out of the book chunk JSONL."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _write_jsonl(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for item in items:
            stream.write(json.dumps(item, ensure_ascii=False) + "\n")


def split_table_chunks(book_path: Path, tables_path: Path) -> tuple[int, int]:
    """Move chunks with a structural table schema to tables_path.

    Existing table chunks in either file are combined; non-table chunks remain
    in book_path. The operation stages and validates both outputs before replace.
    """
    book_chunks = _read_jsonl(book_path)
    table_chunks = _read_jsonl(tables_path) if tables_path.exists() else []

    def is_table(chunk: dict[str, Any]) -> bool:
        return chunk.get("type") == "table" and isinstance(chunk.get("rows"), list) and isinstance(chunk.get("columns"), list)

    moved = [chunk for chunk in book_chunks if is_table(chunk)]
    retained = [chunk for chunk in book_chunks if not is_table(chunk)]
    combined_tables = table_chunks + moved

    ids = [chunk.get("chunk_id") for chunk in combined_tables]
    if any(not chunk_id for chunk_id in ids) or len(ids) != len(set(ids)):
        raise ValueError("Missing or duplicate chunk_id in table output")

    book_tmp = book_path.with_name(book_path.name + ".tmp")
    tables_tmp = tables_path.with_name(tables_path.name + ".tmp")
    _write_jsonl(book_tmp, retained)
    _write_jsonl(tables_tmp, combined_tables)
    # Verify staging files parse and preserve item counts before replacing inputs.
    staged_book = _read_jsonl(book_tmp)
    staged_tables = _read_jsonl(tables_tmp)
    if len(staged_book) != len(retained) or len(staged_tables) != len(combined_tables):
        book_tmp.unlink(missing_ok=True)
        tables_tmp.unlink(missing_ok=True)
        raise ValueError("Staged JSONL validation failed")
    book_tmp.replace(book_path)
    tables_tmp.replace(tables_path)
    return len(moved), len(combined_tables)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book", type=Path, default=Path("data/processed/book.chunks.jsonl"))
    parser.add_argument("--tables", type=Path, default=Path("data/processed/books.chunks.table.jsonl"))
    args = parser.parse_args()
    moved, total_tables = split_table_chunks(args.book, args.tables)
    print(f"Table chunks moved from book file: {moved}")
    print(f"Total table chunks in table file: {total_tables}")
    print(f"Non-table chunks retained in: {args.book}")
    print(f"Table chunks saved to: {args.tables}")


if __name__ == "__main__":
    main()
