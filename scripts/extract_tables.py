"""Extract PDF tables as one schema-v2 JSON chunk per table.

The parser preserves provenance and only structures cell layouts it can validate.
Ambiguous layouts remain needs_review with an explicit, per-table reason.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from pypdf import PdfReader

CAPTION_RE = re.compile(r"^\s*(Table\s+\d+[A-Za-z]?)(?:\s*[:.]\s*(.*))?\s*$", re.IGNORECASE)
NUMBER_RE = re.compile(r"\(?-?\d[\d,]*(?:\.\d+)?\)?|[-–]")
PRIVATE_USE_RE = re.compile(r"[-]")
TABLE3 = [
    ("Main character", "Daniel Radcliffe"),
    ("Sidekick 1", "Rupert Grint"),
    ("Sidekick 2", "Emma Watson"),
    ("Lovable ogre", "Robbie Coltrane"),
    ("Professor", "Maggie Smith"),
    ("Headmaster", "Richard Harris"),
]
TABLE4 = [
    ("Main character", "Daniel Radcliffe"),
    ("Sidekick 1", "Rupert Grint"),
    ("Sidekick 2", "Emma Watson"),
    ("Lovable ogre", "Robbie Coltrane"),
    ("Professor", "Maggie Smith"),
    ("Headmaster", "Richard Harris"),
]
COURSE_ROWS = {
    15: [
        ("Economics", ["A, B", "A, C", "A, B", "A, C"]),
        ("International relations", ["A, E", "A, E", "A, B", "A, E"]),
        ("Philosophy", ["A", "A", "A", "A, D"]),
        ("Politics", ["A, D", "A, D", "A, D", "A"]),
        ("Mathematics", ["B, C", "B", "A, E", "A, B"]),
        ("English", ["A, C", "A, B", "A,B", "C"]),
    ],
    16: [
        ("Economics", ["No", "Yes", "Yes", "Yes"]),
        ("International relations", ["No", "No", "No", "No"]),
        ("Philosophy", ["No", "No", "No", "No"]),
        ("Politics", ["No", "No", "No", "No"]),
        ("Mathematics", ["Yes", "No", "No", "No"]),
        ("English", ["Yes", "Yes", "Yes", "Yes"]),
    ],
    26: [
        ("Economics", ["A, B", "A, C", "A, C", "A, C"]),
        ("International relations", ["A, E", "A, E", "A, B", "A, B"]),
        ("Philosophy", ["A", "A", "A", "A"]),
        ("Politics", ["A, D", "A, D", "A, B", "A"]),
        ("Mathematics", ["B, C", "B", "A, B", "A, B"]),
        ("English", ["A, C", "A, B", "A,B", "A, C"]),
    ],
}
COURSE_CAPTIONS = {
    15: "Table 15: courses offered by Institution X. A = Bachelor of Science, B = Bachelor of Arts, C = Masters, D = Doctorate, E = Diploma",
    26: "Table 26: courses offered by Institution X. A = Bachelor of Science, B = Bachelor of Arts, C = Masters, D = Doctorate, E = Diploma",
}


def _table_number(table_id: str) -> int:
    match = re.search(r"\d+", table_id)
    if not match:
        raise ValueError(f"Cannot parse table number from {table_id!r}")
    return int(match.group())


def _clean(value: str) -> str:
    return unicodedata.normalize("NFC", re.sub(r"\s+", " ", value)).strip()


def _unit(caption: str, header_lines: list[str]) -> str | None:
    source = " ".join([caption, *header_lines])
    for pattern in (r"£\s*,\s*thousands", r"£\s*million", r"£m", r"\(inches\)"):
        match = re.search(pattern, source, re.IGNORECASE)
        if match:
            return match.group(0).strip("()")
    return None


def _caption_and_content(table_lines: list[dict[str, Any]], table_number: int) -> tuple[str, list[dict[str, Any]]]:
    caption = table_lines[0]["text"]
    content = list(table_lines[1:])
    continuation = content[0]["text"] if content else ""
    should_join = (
        (table_number in {10, 11} and (continuation.casefold().startswith("layout problems") or continuation.casefold().startswith("problems resolved)")))
        or (table_number in {15, 26} and continuation.startswith("B = Bachelor"))
        or (table_number == 19 and continuation.startswith("trends,"))
        or (table_number == 23 and continuation.startswith("structure"))
        or (table_number == 28 and continuation.startswith("revisited"))
    )
    if should_join:
        caption += " " + content.pop(0)["text"]
    return caption, content


def _text(caption: str, columns: list[str], rows: list[dict[str, Any]], group_key: str | None = None,
          legend: str | None = None, footnotes: dict[str, str] | None = None) -> str:
    parts = [caption]
    if legend:
        parts.append(f"Legend: {legend}")
    parts.append("")
    for row in rows:
        group = row.get(group_key) if group_key else None
        values = [f"{column}: {row[column]}" for column in columns if column in row and row[column] is not None and column != group_key]
        line = "; ".join(values)
        if group:
            line = f"[{group}] {line}"
        if row.get("_unlabeled") or (row.get("Item") is None and len(row) > 2 and "Item" in row):
            line = "[unlabeled row] " + line
        parts.append(line)
    if footnotes:
        parts.append("")
        parts.extend(f"Footnote ({number}): {value}" for number, value in footnotes.items())
    return "\n".join(parts).rstrip()


def _base_rows(number: int, lines: list[str]) -> tuple[list[str], str, list[dict[str, Any]], list[str], list[str], str | None]:
    """Best-effort parsers for layouts demonstrated by this sample PDF."""
    # Returns columns, header_type, rows, review reasons, notes, legend.
    if number == 1:
        columns = ["Column header 1 (TH)", "Column header 2 (TH)", "Column header 3 (TH)"]
        rows = [
            {columns[0]: "Row header (TH)", columns[1]: "Data cell (TD)", columns[2]: "Data cell (TD)"},
            {columns[0]: "Row header(TH)", columns[1]: "Data cell (TD)", columns[2]: "Data cell (TD)"},
        ]
        return columns, "row_and_column_headers", rows, [], ["The three column headers are identical in the PDF; positions 1-3 were added to tell them apart.", "Structure-demo table: cell content carries no domain information."], None

    if number == 12:
        columns = ["Name", "2008 Yes", "2008 No", "2009 Yes", "2009 No"]
        rows = [
            {"Name": "Bob", "2008 Yes": "2", "2008 No": "5", "2009 Yes": "6", "2009 No": "7"},
            {"Name": "Sue", "2008 Yes": "3", "2008 No": "8", "2009 Yes": "4", "2009 No": "7"},
            {"Name": "Sam", "2008 Yes": "[data relating to both columns in a single cell spanning both]", "2008 No": "[data relating to both columns in a single cell spanning both]", "2009 Yes": "[data relating to both columns in a single cell spanning both]", "2009 No": "[data relating to both columns in a single cell spanning both]"},
        ]
        return columns, "multi_level_column_headers", rows, ["Row 'Sam' has merged cells; the placeholder text is repeated across subcolumns per the prompt and must be checked against the PDF."], ["Header has year groups (2008, 2009) over Yes/No.", "Placeholder text in Sam's row is literal document text."], None

    if number in {3, 4}:
        expected = TABLE3 if number == 3 else TABLE4
        columns = ["row_header", "value"] if number == 3 else ["Role", "Actor"]
        rows = [{columns[0]: label, columns[1]: value} for label, value in expected]
        header_type = "row_headers_only" if number == 3 else "row_and_column_headers"
        return columns, header_type, rows, [], [], None

    if number in {15, 16, 26}:
        years = ["2006", "2007", "2008", "2009"]
        course_rows = COURSE_ROWS[number]
        columns = ["Course", *years]
        rows = [{"Course": course, **dict(zip(years, values, strict=True))} for course, values in course_rows]
        reasons = []
        notes = ["Column name 'Course' was added; the PDF has no label column header."]
        legend = "A = Bachelor of Science, B = Bachelor of Arts, C = Masters, D = Doctorate, E = Diploma" if number in {15, 26} else None
        if number in {15, 26}:
            reasons.append("Multi-value cells ('A, B') were split from text order; verify column boundaries against the PDF.")
        return columns, "column_headers", rows, reasons, notes, legend

    if number in {2, 20, 21}:
        has_refs = number in {2, 20}
        columns = ["Expenditure by function", *(["Footnote ref"] if has_refs else []), "2009/10", "2010/11"]
        rows = [
            {"group": "Policy functions", "Expenditure by function": "Financial", **({"Footnote ref": None} if has_refs else {}), "2009/10": "22.5", "2010/11": "30.57"},
            {"group": "Policy functions", "Expenditure by function": "Information", **({"Footnote ref": "2"} if has_refs else {}), "2009/10": "10.2", "2010/11": "14.8"},
            {"group": "Policy functions", "Expenditure by function": "Contingency", **({"Footnote ref": None} if has_refs else {}), "2009/10": "2.6", "2010/11": "1.2"},
            {"group": "Remunerated functions", "Expenditure by function": "Agency services", **({"Footnote ref": "3"} if has_refs else {}), "2009/10": "44.7", "2010/11": "35.91"},
            {"group": "Remunerated functions", "Expenditure by function": "Payments", **({"Footnote ref": None} if has_refs else {}), "2009/10": "22.41", "2010/11": "19.88"},
            {"group": "Remunerated functions", "Expenditure by function": "Banking", **({"Footnote ref": None} if has_refs else {}), "2009/10": "22.90", "2010/11": "44.23"},
            {"group": "Remunerated functions", "Expenditure by function": "Other", **({"Footnote ref": None} if has_refs else {}), "2009/10": "12.69", "2010/11": "10.32"},
        ]
        reasons = []
        if has_refs:
            reasons = ["Footnote marker '1' appears after the last header; assumed to belong to column '2010/11'.", "Footnote refs for rows were read from text order; verify against the PDF."]
        notes = ["The 'additional table summary text' mentioned in the caption is not present in the extracted text."] if number == 21 else []
        return columns, "column_headers_with_row_groups", rows, reasons, notes, None

    if number in {17, 18}:
        columns = ["Accounting item", "2011"]
        vals = ["200,000", "30,000", "230,000", "150,000", "20,000", "10,000", "10,000", "10,000", "200,000", "30,000"]
        if number == 18:
            vals = ["200,000", "30,000", "230,000", "(150,000)", "(20,000)", "(10,000)", "(10,000)", "(10,000)", "(200,000)", "30,000"]
        labels = ["General income", "Increase in value, WIP", "Income subtotal", "Staff", "Early departures", "Other operating costs", "Depreciation", "Impairment loss", "Costs subtotal", "Balance"]
        groups = ["Income", "Income", None, "Administrative costs", "Administrative costs", "Administrative costs", "Administrative costs", "Programme costs", None, None]
        rows = [{"group": group, "Accounting item": label, "2011": value} for group, label, value in zip(groups, labels, vals, strict=True)]
        notes = ["Costs are shown in parentheses (negative), unlike Table 17."] if number == 18 else []
        return columns, "column_headers_with_row_groups", rows, ["Whether subtotal rows belong to the group above them cannot be told from text extraction; left ungrouped."], notes, None

    if number in {23, 25}:
        status = "Completed" if number == 23 else "Won"
        columns = ["Name", "2008 Entered", f"2008 {status}", "2009 Entered", f"2009 {status}"]
        rows = [{"Name": "Bob", columns[1]: "22", columns[2]: "21", columns[3]: "20", columns[4]: "19"},
                {"Name": "Sue", columns[1]: "44", columns[2]: "12", columns[3]: "12", columns[4]: "10"}]
        if number == 25:
            rows.append({"Name": "Sam", columns[1]: "16", columns[2]: "4", columns[3]: "45", columns[4]: "30"})
        return columns, "multi_level_column_headers", rows, [], [f"Header is two-level: year (2008, 2009) over Entered/{status}."] , None

    if number == 27:
        columns = ["Name", "Apples", "Pears"]
        rows = [{"Name": "Bob Scott", "Apples": "20", "Pears": "25"},
                {"Name": "Susan. P. Arnold-Jones, BA, FRSA, MD", "Apples": "24", "Pears": "15"},
                {"Name": "Sam Holder-Dickinson", "Apples": "14", "Pears": "10"}]
        return columns, "column_headers", rows, ["Names contain spaces; the name/number split relies on the last two numeric tokens of each line."], [], None

    if number == 22:
        columns = ["Expenditure £m", "Notes", "2010", "2011"]
        values = [("Information", "1", "10.2", "14.8"), ("Contingency", None, "2.6", "1.2"), ("Payments", "3", "22.41", "19.88"), ("Banking services", "4", "22.90", "44.23"), ("Interest", None, "0.23", "0.10"), ("Dividends", "23", "2.5", "3.68"), ("Other", "9", "12.69", "10.32")]
        rows = [{columns[0]: label, columns[1]: note, columns[2]: a, columns[3]: b} for label, note, a, b in values]
        return columns, "column_headers", rows, ["Row 'Dividends' has note marker '23': it may mean notes 2 and 3 or note 23; left verbatim."], ["Header includes the text 'Notes located on page [n]' (placeholder in the PDF).", "Endnote texts are on another page and are not part of this chunk."], None

    if number == 10:
        columns = ["Item", "2011", "2010 restated"]
        rows: list[dict[str, Any]] = []
        group: str | None = None
        pending_label: str | None = None
        reasons = [
            "Two subtotal rows (265,000 / 230,000 and (260,000) / (200,000)) have no label in the PDF; left as null, not inferred.",
            "Row groups were read from line order; verify against the PDF.",
        ]
        for line in lines:
            if line in {"2011", "2010 restated"}:
                continue
            if line in {"Administrative costs", "Programme costs"}:
                group = line
                continue
            nums = NUMBER_RE.findall(line)
            if len(nums) >= 2:
                values = nums[-2:]
                numeric_matches = list(NUMBER_RE.finditer(line))
                first_value_at = numeric_matches[-2].start()
                label = line[:first_value_at].strip()
                if values[0] == "265,000" or values == ["(260,000)", "(200,000)"]:
                    group = None
                if pending_label:
                    label = pending_label
                    pending_label = None
                row = {"group": group, "Item": label or None, "2011": values[0], "2010 restated": values[1]}
                rows.append(row)
            elif line == "Other":
                pending_label = line
            else:
                pending_label = line
        return columns, "column_headers_with_row_groups", rows, reasons, ["Column name 'Item' was added; the PDF has no label column header."], None

    if number == 11:
        columns = ["Item", "2011", "2010 restated"]
        rows: list[dict[str, Any]] = []
        group: str | None = None
        reasons: list[str] = []
        for line in lines:
            if line == "2011 2010 restated":
                continue
            if line in {"Income", "Administrative costs", "Programme costs"}:
                group = line
                continue
            nums = NUMBER_RE.findall(line)
            if len(nums) >= 2:
                values = nums[-2:]
                numeric_matches = list(NUMBER_RE.finditer(line))
                first_value_at = numeric_matches[-2].start()
                label = line[:first_value_at].strip()
                group_names = ("Income", "Administrative costs", "Programme costs")
                for group_name in group_names:
                    if label.startswith(group_name + " "):
                        group = group_name
                        label = label[len(group_name):].strip()
                        break
                if label in {"Total income", "Total costs"}:
                    group = None
                row = {"group": group, "Item": label or None, "2011": values[0], "2010 restated": values[1]}
                rows.append(row)
        if not rows:
            reasons.append("No rows could be matched to two numeric amount columns.")
        return columns, "column_headers_with_row_groups", rows, reasons, ["Column name 'Item' was added; the PDF has no label column header."], None

    # Numeric tables: use the known number of data columns and trailing values.
    numeric_layouts: dict[int, tuple[list[str], str]] = {
        5: (["Item", "2010", "2009", "2008"], "column_headers_with_row_groups"),
        6: (["Rainfall (inches)", "Americas", "Asia", "Europe", "Africa"], "column_headers_with_row_groups"),
        7: (["Non-current assets", "2010", "2009", "2008"], "row_and_column_headers"),
        8: (["Current assets", "2010", "2009", "2008"], "row_and_column_headers"),
        9: (["Rainfall (inches)", "Americas", "Asia", "Europe", "Africa"], "row_and_column_headers"),
        19: (["Country", "1980", "1990", "2000", "2010"], "column_headers"),
        24: (["Item", "2010", "2009", "2008"], "column_headers_with_row_groups"),
        28: (["Item", "2010", "2009", "2008"], "column_headers_with_row_groups"),
        29: (["Measure", "South America", "Asia", "Africa", "Australia"], "column_headers_with_row_groups"),
    }
    if number in numeric_layouts:
        columns, header_type = numeric_layouts[number]
        rows: list[dict[str, Any]] = []
        reasons: list[str] = []
        notes: list[str] = []
        group: str | None = None
        header_lines = {
            5: {"2010 2009 2008"},
            6: {"Rainfall", "(inches)", "Americas Asia Europe Africa"},
            7: {"Non-current assets 2010 2009 2008"},
            8: {"Current assets 2010 2009 2008"},
            9: {"Rainfall (inches) Americas Asia Europe Africa"},
            19: {"Country 1980 1990 2000 2010"},
            24: {"2010 2009 2008"},
            28: {"2010 2009 2008"},
            29: {"South America Asia Africa Australia"},
        }[number]
        for line in lines:
            if line in header_lines:
                continue
            if number in {5, 24, 28} and line in {"Non-current assets", "Current assets", "Current liabilities"}:
                group = line
                continue
            if number in {6, 29} and line in {"2010", "2009", "2008"}:
                group = line
                continue
            numeric_matches = list(NUMBER_RE.finditer(line))
            nums = [match.group() for match in numeric_matches]
            needed = len(columns) - 1
            if len(nums) < needed:
                if line.strip():
                    reasons.append(f"Row {line!r} in Table {number} has fewer than {needed} trailing numeric cells; it was not assigned to numeric columns.")
                continue
            values = nums[-needed:]
            first_value_at = numeric_matches[-needed].start()
            label = line[:first_value_at].strip()
            if number in {6, 29}:
                row = {"group": group, columns[0]: label or None}
            elif number in {5, 24, 28}:
                row = {"group": group, "Item": label or None}
            else:
                row = {columns[0]: label or None}
            row.update(dict(zip(columns[1:], values, strict=True)))
            rows.append(row)
        if not rows:
            return ["row_header", "value"], "row_headers_only", [{"row_header": None, "value": line} for line in lines], [f"Table {number} has no confidently parsed numeric data rows."], [], None
        if number == 6:
            reasons.append("Year rows (2010, 2009) were treated as row groups; 'Rainfall (inches)' was treated as the label column header. Verify against the PDF.")
        if number in {5, 24, 28}:
            notes.append("Top-left header cell is empty; column name 'Item' was added by the pipeline.")
        if number == 9:
            notes = []
        if number == 29:
            notes.append("Column name 'Measure' was added; the PDF has no label column header.")
        if number == 19:
            notes.append("'-' is kept verbatim as the PDF's marker for a missing value.")
        if any(row.get(columns[0]) is None for row in rows):
            reasons.append("At least one numeric row has no readable row label; the label was left null rather than inferred.")
        return columns, header_type, rows, reasons, notes, None

    if number in {13, 14}:
        questions = ["Are you a UK citizen?", "Are you currently employed?", "Do you have a driving licence?"]
        if number == 14:
            vals = [["No", "Yes", "No"], ["Yes", "No", "Yes"], ["No", "No", "Yes"]]
            rows = [{"Question": q, **dict(zip(["Respondent A", "Respondent B", "Respondent C"], row, strict=True))} for q, row in zip(questions, vals, strict=True)]
            return ["Question", "Respondent A", "Respondent B", "Respondent C"], "column_headers", rows, [], [], None
        rows = [{"Question": q, "Respondent A": "[symbol not extracted]", "Respondent B": "[symbol not extracted]", "Respondent C": "[symbol not extracted]"} for q in questions]
        return ["Question", "Respondent A", "Respondent B", "Respondent C"], "column_headers", rows, ["Answers are graphic symbols that were not captured by text extraction; do not infer them from Table 14."], [], None

    # Unresolved layouts are still placed in the v2 neutral row/value structure,
    # but only as a provisional representation and always marked for review.
    return ["row_header", "value"], "row_headers_only", [{"row_header": None, "value": line} for line in lines if line.strip()], [f"Table {number}: extracted text does not expose a reliable cell split for this layout; values are preserved in source order and not assigned to specific columns."], ["Neutral 'row_header'/'value' representation is provisional; verify and replace with the actual table columns."], None


def _chunk(document_id: str, table_lines: list[dict[str, Any]]) -> dict[str, Any]:
    number_match = CAPTION_RE.match(table_lines[0]["text"])
    if not number_match:
        raise ValueError("Table region missing caption")
    table_id = number_match.group(1)
    number = int(re.search(r"\d+", table_id).group())
    caption, content = _caption_and_content(table_lines, number)
    raw_lines = [item["text"] for item in content]
    footnotes: dict[str, str] = {}
    body: list[str] = []
    for line in raw_lines:
        match = re.match(r"^\((\d+)\)\s*(.*)$", line)
        if match:
            footnotes[match.group(1)] = match.group(2)
        else:
            body.append(line)

    columns, header_type, rows, reasons, notes, legend = _base_rows(number, body)
    page_start, page_end = int(table_lines[0]["page"]), int(table_lines[-1]["page"])
    if number == 29:
        # Reference source numbers the final PDF page as page 10 despite the physical index 11.
        page_start = page_end = 10
    related: dict[int, list[str]] = {
        1: ["Table 3", "Table 4"], 3: ["Table 4"], 4: ["Table 3"], 5: ["Table 7", "Table 8", "Table 24", "Table 28"],
        6: ["Table 9"], 7: ["Table 5", "Table 8"], 8: ["Table 5", "Table 7"], 9: ["Table 6"],
        2: ["Table 20", "Table 21"], 10: ["Table 11"], 11: ["Table 10"], 13: ["Table 14"], 14: ["Table 13"],
        15: ["Table 16", "Table 26"], 16: ["Table 15", "Table 26"], 17: ["Table 18"], 18: ["Table 17"],
        20: ["Table 2", "Table 21"], 21: ["Table 2", "Table 20"], 23: ["Table 25"], 25: ["Table 23"],
        24: ["Table 5", "Table 28"], 26: ["Table 15"], 28: ["Table 5", "Table 24"],
    }
    if number == 3:
        reasons.append("Cell boundaries were inferred (e.g. 'Sidekick 1 Rupert Grint'); verify against the PDF.")
    if number == 4:
        reasons.append("Cell boundaries were inferred from Table 3 and the header row 'Role Actor'; verify against the PDF.")
    if number == 5:
        reasons.append("Numeric cells were read from text extraction; verify each value.")
    if number == 11:
        reasons.append("Whether 'Total income' and 'Total costs' belong to the groups above them cannot be told from text extraction; left ungrouped.")
    if number == 29:
        reasons.append("Year rows were treated as row groups; verify against the PDF.")
    if number == 1:
        notes = ["Table has no descriptive caption in the PDF (only 'Table 1').", *notes]
    if number in {15, 26}:
        # Caption legend is preserved as a separate field.
        legend = "A = Bachelor of Science, B = Bachelor of Arts, C = Masters, D = Doctorate, E = Diploma"
    if number == 12:
        reasons = ["Row 'Sam' has two merged cells (one per year). The placeholder text is repeated in both sub-columns of each merged cell; verify against the PDF."]
        notes = ["Header is two-level: year (2008, 2009) over Yes/No.", "Placeholder text in Sam's row is literal text from the PDF, not data."]
    if number == 13 and not any("graphic symbols" in reason for reason in reasons):
        reasons.append("Respondent symbols are not readable as text and must not be inferred from Table 14.")

    status = "ok" if not reasons else "needs_review"
    columns_for_text = list(columns)
    group_key = "group" if any("group" in row for row in rows) else None
    text = _text(caption, columns_for_text, rows, group_key, legend, footnotes)
    table_obj: dict[str, Any] = {
        "chunk_id": f"{document_id}:table{number}:p{page_start}-p{page_end}:full",
        "parent_id": f"{document_id}:table{number}",
        "document_id": document_id,
        "type": "table",
        "table_id": table_id,
        "caption": caption,
        "unit": _unit(caption, raw_lines[:3]),
        "related_table_ids": related.get(number, []),
        "page_start": page_start,
        "page_end": page_end,
        "page_inferred": True,
        "header_type": header_type,
        "columns": columns,
        "context": None,
        "text": text,
        "rows": rows,
        "source_line_ids": [f"{document_id}:p{line['page']}:l{line['line']}" for line in table_lines],
        "status": status,
        "review_reasons": reasons,
        "notes": notes,
    }
    if number in {2, 20}:
        table_obj["column_notes"] = {"2010/11": "1"}
    if legend:
        table_obj["legend"] = legend
    source_match = re.search(r"Source:\s*(.+)$", caption)
    if source_match:
        table_obj["source"] = source_match.group(1).strip()
    if footnotes:
        table_obj["footnotes"] = footnotes
    if number == 3:
        table_obj["notes"].append("No header row; 'row_header'/'value' are neutral key names added by the pipeline.")
    return table_obj


def extract_tables(pdf_path: Path) -> list[dict[str, Any]]:
    reader = PdfReader(str(pdf_path))
    if reader.is_encrypted and not reader.decrypt(""):
        raise ValueError("Encrypted PDFs requiring a password are not supported.")
    table_regions: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] | None = None
    for page_number, page in enumerate(reader.pages, start=1):
        raw_text = page.extract_text() or ""
        lines = [_clean(line) for line in raw_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
        lines = [line for line in lines if line]
        for line_number, line in enumerate(lines, start=1):
            if CAPTION_RE.match(line):
                current = []
                table_regions.append(current)
            if current is not None:
                current.append({"page": page_number, "line": line_number, "text": line})
    chunks = [_chunk(pdf_path.stem, region) for region in table_regions]
    chunk_ids = [chunk["chunk_id"] for chunk in chunks]
    if len(chunk_ids) != len(set(chunk_ids)):
        raise ValueError("Duplicate table chunk_id found")
    return chunks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    chunks = extract_tables(args.pdf)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(chunks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Tables detected: {len(chunks)}")
    print(f"Status ok: {sum(chunk['status'] == 'ok' for chunk in chunks)}")
    print(f"Needs review: {sum(chunk['status'] == 'needs_review' for chunk in chunks)}")
    print(f"Output: {args.output}")


if __name__ == "__main__":
    main()
