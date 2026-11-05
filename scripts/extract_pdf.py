"""Extract page-local PDF text into auditable JSONL with line provenance.

This starter intentionally does not OCR image-only pages. It records those pages
for review rather than treating them as empty evidence.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

from pypdf import PdfReader


def clean_line(value: str) -> str:
    """Normalize Unicode and whitespace without changing source language."""
    value = unicodedata.normalize("NFC", value)
    value = value.replace("­", "")  # soft hyphen from PDF layout
    return re.sub(r"\s+", " ", value).strip()


def classify_page(page_number: int, lines: list[str]) -> str:
    """Assign a conservative page category for review and retrieval policy."""
    joined = " ".join(lines).lower()
    if page_number == 1 or "practical natural language processing" in joined and page_number <= 2:
        return "cover"
    if "table of contents" in joined or (page_number in range(9, 16) and "part i" in joined):
        return "toc"
    if not lines:
        return "image_only_or_empty"
    if page_number <= 16:
        return "front_matter"
    return "content"


def is_running_footer(line: str) -> bool:
    """Match repeated running footers, excluding table captions."""
    value = line.strip()
    match = re.match(r"^(\d+)\s*\|\s*Chapter\s+(\d+)\s*:\s*(.+)$", value, re.IGNORECASE)
    if match:
        return True
    match = re.match(r"^(\d+)\s*\|\s*Chapter\s+(\d+)\s+(.+)$", value, re.IGNORECASE)
    if match:
        printed_page, chapter, title = match.groups()
        return int(printed_page) != int(chapter) and "table" not in title.casefold()
    if "|" not in value:
        return False
    if value.count("|") == 1 and re.match(r"^.+\s\|\s\d+$", value):
        return True
    return bool(re.match(r"^Chapter\s+\d+\s*:\s*.+\|\s*\d+$", value, re.IGNORECASE))


def extract(pdf_path: Path, output: Path, report_path: Path) -> dict:
    reader = PdfReader(str(pdf_path))
    if reader.is_encrypted:
        raise ValueError("Encrypted PDFs are not supported by this script.")

    report = {
        "source_file": pdf_path.name,
        "page_count": len(reader.pages),
        "pages": [],
        "notes": [
            "Page numbers are 1-based PDF page indices, not printed book page labels.",
            "Line numbers are generated per page from extracted text and may not match visual lines.",
            "No OCR or image understanding is performed; image-only pages are flagged.",
            "Layout-sensitive line joining is conservative; repeated running footer patterns are removed and counted in the page audit.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    with output.open("w", encoding="utf-8", newline="\n") as out:
        for page_number, page in enumerate(reader.pages, start=1):
            raw_text = page.extract_text() or ""
            normalized = unicodedata.normalize("NFC", raw_text).replace("\r\n", "\n").replace("\r", "\n")
            extracted_lines = [clean_line(line) for line in normalized.split("\n")]
            lines = [line for line in extracted_lines if line and not is_running_footer(line)]
            removed_footer_count = sum(bool(line) and is_running_footer(line) for line in extracted_lines)
            images = len(getattr(page, "images", []))
            page_record = {
                "page": page_number,
                "extracted_chars": len(raw_text),
                "line_count": len(lines),
                "removed_running_footer_lines": removed_footer_count,
                "image_count": images,
                "page_type": classify_page(page_number, lines),
                "status": "text_extracted" if lines else ("image_only_or_empty" if images else "no_text"),
            }
            report["pages"].append(page_record)

            for line_number, text in enumerate(lines, start=1):
                row = {
                    "document_id": pdf_path.stem,
                    "page": page_number,
                    "line": line_number,
                    "text": text,
                    "source_text": text,
                    "source_file": pdf_path.name,
                    "extraction": "pypdf",
                }
                out.write(json.dumps(row, ensure_ascii=False) + "\n")

    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="Destination JSONL")
    parser.add_argument("--report", type=Path, required=True, help="Destination page audit JSON")
    args = parser.parse_args()
    report = extract(args.pdf, args.output, args.report)
    empty = [p["page"] for p in report["pages"] if p["line_count"] == 0]
    image_pages = [p["page"] for p in report["pages"] if p["image_count"] > 0]
    print(f"Pages: {report['page_count']}")
    print(f"Extracted lines: {sum(p['line_count'] for p in report['pages'])}")
    print(f"Pages with images: {len(image_pages)}")
    print(f"Pages with no extracted text: {len(empty)} ({empty[:25]})")
    print(f"JSONL: {args.output}")
    print(f"Audit report: {args.report}")


if __name__ == "__main__":
    main()
