"""Create reviewable text chunks while preserving page/line source mappings."""
from __future__ import annotations

import re
from typing import Any

HEADING_RE = re.compile(
    r"^(?:chapter\s+\d+|part\s+[ivx]+|\d+(?:\.\d+)*\.?\s+|"
    r"(?:contents|foreword|preface|index|references|bibliography|wrapping up|applications|unique challenges)\s*$)",
    re.IGNORECASE,
)
LIST_RE = re.compile(r"^(?:[-*•▪]|\(?\d+[.)]|[A-Za-z][.)])\s+")
HYPHEN_CHARS = ("-", "‐", "­")
TABLE_EXIT_PREFIXES = (
    "Apart from the list of metrics",
    "In the case of classification tasks",
    "Ranking tasks like information search",
    "When it comes to text-generation tasks",
    "However, any evaluation scheme",
)
METRIC_NAME_RE = re.compile(
    r"^(Accuracy|Precision|Recall|F1\s+score|AUC|MRR|MAPE|MAP|RMSE|BLEU|METEOR|ROUGE|Perplexity)\b",
    re.IGNORECASE,
)
METRIC_START_RE = re.compile(
    r"^(Accuracy|Precision|Recall|F1\s+score|AUC|MRR|MAPE|MAP|RMSE|BLEU|METEOR|ROUGE|Perplexity)"
    r"(?:\s+\([^)]*\))*\s+\[\d+\]",
    re.IGNORECASE,
)
APPLICATION_PREFIXES: dict[str, tuple[str, ...]] = {
    "accuracy": ("Mainly used",),
    "precision": ("Used in various",),
    "recall": ("Used in classification",),
    "f1 score": ("Used simultaneously",),
    "auc": ("Used to measure",),
    "mrr": ("Used heavily",),
    "map": ("Used in ranked",),
    "rmse": ("Used in conjunction",),
    "mape": ("Used when",),
    "bleu": ("Mainly used",),
    "rouge": ("Since it measures",),
    "perplexity": ("Used to evaluate",),
}


ROW_SPLIT_SPECS: dict[str, dict[str, Any]] = {
    # Table 2-3, PDF page 103.
    "Table 2-3.": {
        "labels": ("Project attribute", "Decision paths", "Examples"),
        "rows": [
            ("More training data", ["More training data is generated post-deployment.",
             "Once deployed, extracted signals can be used to automatically improve the model. Can also try online learning to train the model automatically on a daily basis.",
             "Abuse-detection systems where users flag data."]),
            ("Training data is not", ["Training data is not generated post-deployment.",
             "Manual labeling could be done to improve evaluation and the models. Ideally, each new model has to be manually built and evaluated.",
             "A subset of a larger NLP pipeline with no direct feedback."]),
            ("Low model latency is required", ["Low model latency is required, or model has to be online with near-real-time response.",
             "Need to use models that can be inferred quickly. Another option is to create memoization strategies like caching or have substantially bigger computing power.",
             "Systems that need to respond right away, like any chatbot or an emergency tracking system."]),
            ("Low model latency is not", ["Low model latency is not required, or model can be run in an offline fashion.",
             "Can use more advanced and slower models. This can also help in optimizing costs where feasible.",
             "Systems that can be run on a batch process, like retail product catalog analysis."]),
        ],
        "header": "Project attribute Decision paths Examples",
        "end_prefix": "Working with Other Languages",
    },
    # Table 2-4, PDF page 104. Caption spans two extra lines before the header.
    "Table 2-4.": {
        "labels": ("Language attribute", "Example and languages", "Action"),
        "rows": [
            ("High-resource", ["High-resource languages",
             "Languages that have both ample data as well as pre-built models. Examples include English, French, and Spanish.",
             "Possible to use pre-trained DL models. Easier to use."]),
            ("Low-resource", ["Low-resource languages",
             "Languages that have limited data and recent digital adoption. May not have pre-built models. Examples include Swahili, Burmese, and Uzbek.",
             "Depending on the task, may need to label more data as well as explore individual components."]),
            ("Morphologically", ["Morphologically rich",
             "Linguistic and grammatical information like subject, object, predicate, tense, and mode are not separate words, but are joined together. Examples include Latin, Turkish, Finnish, and Malayalam.",
             "If the language is not resource rich, we’ll need to explore morphological analyzers that exist for the language. In the worst case, manual rules to handle certain cases might be needed."]),
            ("Vocabulary", ["Vocabulary variation heavy",
             "Nonstandard spellings and high word variation. For Arabic and Hindi, the spellings are nonstandard.",
             "If the language is not resource rich, then we may need to first normalize the words/spellings before training any model. This may not be needed for languages with large datasets, as they can still learn of vocabulary variation."]),
            ("CJK languages", ["CJK languages",
             "These languages are derived from ancient Chinese characters. They’re not alphabet based and have several thousand characters for basic literacy and over 40,000 characters for larger coverage. Thus, they have to be handled differently. They include Chinese, Japanese, and Korean, hence the name CJK.",
             "Use specific tokenization schemes in these languages. Given that an ample amount of CJK data is available, it’s possible to build NLP models for various tasks from scratch. There are also pre-trained models for them. Transfer learning from models trained in other languages beyond CJK may not be useful in this case."]),
        ],
        "header": "Example and languages Action",
        "end_prefix": "Next, we’ll turn our attention",
    },
    # Table 3-2, PDF page 121.
    "Table 3-2.": {
        "labels": ("Word", "TF score", "IDF score", "TF-IDF score"),
        "rows": [
            ("dog ", ["dog", "⅓ = 0.33", "log2(4/3) = 0.4114", "0.4114 * 0.33 = 0.136"]),
            ("bites ", ["bites", "⅙ = 0.17", "log2(4/2) = 1", "1* 0.17 = 0.17"]),
            ("man ", ["man", "0.33", "log2(4/3) =0.4114", "0.4114 * 0.33 = 0.136"]),
            ("eats ", ["eats", "0.17", "log2(4/2) =1", "1* 0.17 = 0.17"]),
            ("meat ", ["meat", "1/12 = 0.083", "log2(4/1) =2", "2* 0.083 = 0.17"]),
            ("food ", ["food", "0.083", "log2(4/1) =2", "2* 0.083 = 0.17"]),
        ],
        "header": "Word TF score IDF score TF-IDF score",
        "end_prefix": "The TF-IDF vector representation",
    },
    # Table 6-1, PDF page 229.
    "Table 6-1.": {
        "labels": ("Questions", "Answer"),
        "rows": [
            ("What can I do", ["What can I do with Amazon Machine Learning? How can I use Amazon Machine Learning? What can Amazon Machine Learning do?",
             "You can use Amazon Machine Learning to create a wide variety of predictive applications. For example, you can use Amazon Machine Learning to help you build applications that flag suspicious transactions, detect fraudulent orders, forecast demand, etc."]),
            ("What algorithm does", ["What algorithm does Amazon Machine Learning use to generate models? How does Amazon Machine Learning build models?",
             "Amazon Machine Learning currently uses an industry-standard logistic regression algorithm to generate models."]),
            ("Are there limits", ["Are there limits to the size of the dataset I can use for training? What is the maximum size of training dataset?",
             "Amazon Machine Learning can train models on datasets up to 100 GB in size."]),
        ],
        "header": "Questions Answer",
        "end_prefix": "Figure 6-1 is a working version",
    },
    # Table 7-1, PDF page 271.
    "Table 7-1.": {
        "labels": ("NLP task", "Use", "Nature of data"),
        "rows": [
            ("Search ", ["Search", "Find relevant content for a given user query.", "World wide web/large collection of documents"]),
            ("Topic modeling", ["Topic modeling", "Find topics and hidden patterns in a set of documents.", "Large collection of documents"]),
            ("Text summarization", ["Text summarization", "Create a shorter version of the text with the most important content", "Typically a single document"]),
            ("Recommendations", ["Recommendations", "Showing related articles", "Large collection of documents"]),
            ("Machine translation", ["Machine translation", "Translate from one language to another", "A single document"]),
            ("Question answering", ["Question answering system", "Get answers to queries directly instead of a set of documents.", "A single document or a large collection of documents"]),
        ],
        "header": "NLP task Use Nature of data",
        "end_prefix": "With this overview",
    },
    # Table 2-1, PDF page 97. Field values were split from the extracted text and
    # must reproduce its words (see split_row_spec_groups). A field left as "" is
    # omitted from the rendered chunk.
    "Table 2-1.": {
        "labels": ("Data attribute", "Decision path", "Examples"),
        "rows": [
            ("Large data volume", ["Large data volume",
             "Can use techniques that require more data, like DL. Can use a richer set of features as well. If the data is sufficiently large but unlabeled, we can also apply unsupervised techniques.",
             "If we have a lot of reviews and metadata associated with them, we can build a sentiment-analysis tool from scratch."]),
            ("Small data volume", ["Small data volume",
             "Need to start with rule-based or traditional ML solutions that are less data hungry. Can also adapt cloud APIs and generate more data with weak supervision. We can also use transfer learning if there’s a similar task that has large data.",
             "This often happens at the start of a completely new project."]),
            ("Data quality is poor", ["Data quality is poor and the data is heterogeneous in nature",
             "More data cleaning and pre-processing might be required.",
             "This entails issues like code mixing (different languages being mixed in the same sentence), unconventional language, transliteration, or noise (like social media text)."]),
            ("Data quality is good", ["Data quality is good",
             "Can directly apply off-the-shelf algorithms or cloud APIs more easily.",
             "Legal text or newspapers."]),
            ("Data consists of full-", ["Data consists of full-length documents",
             "Choose the right strategy for breaking the document into lower levels, like paragraphs, sentences, or phrases, depending on the problem.",
             "Document classification, review analysis, etc."]),
        ],
        "header": "Data attribute Decision path Examples",
        "end_prefix": "So far, we’ve seen",
    },
    # Table 3-1, PDF page 115. The extracted text has no column header row, so the
    # labels "Document" and "Text" are inferred, not read from the PDF.
    "Table 3-1.": {
        "labels": ("Document", "Text"),
        "rows": [
            ("D1 ", ["D1", "Dog bites man."]),
            ("D2 ", ["D2", "Man bites dog."]),
            ("D3 ", ["D3", "Dog eats meat."]),
            ("D4 ", ["D4", "Man eats food."]),
        ],
        "header": None,
        "end_prefix": "Lowercasing text and ignoring punctuation",
    },
    # Table 4-1, PDF page 159. No column header row in the extracted text, so the
    # labels "Reason" and "Explanation" are inferred, not read from the PDF.
    "Table 4-1.": {
        "labels": ("Reason", "Explanation"),
        "rows": [
            ("Reason 1", ["Reason 1", "Since we extracted all possible features, we ended up in a large, sparse feature vector, where most features are too rare and end up being noise. A sparse feature set also makes training hard."]),
            ("Reason 2", ["Reason 2", "There are very few examples of relevant articles (~20%) compared to the non-relevant articles (~80%) in the dataset. This class imbalance makes the learning process skewed toward the non-relevant articles category, as there are very few examples of “relevant” articles."]),
            ("Reason 3", ["Reason 3", "Perhaps we need a better learning algorithm."]),
            ("Reason 4", ["Reason 4", "Perhaps we need a better pre-processing and feature extraction mechanism."]),
            ("Reason 5", ["Reason 5", "Perhaps we should look to tuning the classifier’s parameters and hyperparameters."]),
        ],
        "header": None,
        "end_prefix": "Let’s see how to improve our classification",
    },
    # Table 6-2, PDF page 250. Each field list is supplied by the reviewer and is
    # checked against the extracted source text before a chunk is written.
    "Table 6-2.": {
        "labels": ("Dataset", "Domain", "Usage"),
        "rows": [
            ("ATIS [13]", ["ATIS [13]", "Air Ticket Booking",
             "Benchmark for intent classification and slot filling. This is a single-domain dataset, hence entities and intents are restricted to one domain."]),
            ("SNIPS [14]", ["SNIPS [14]", "Multidomain",
             "Benchmark for intent classification and slot filling. This is a multidomain dataset, hence the entities belong to multiple domains. Multiple-domain datasets are challenging to model due their variability."]),
            ("DSTC [15]", ["DSTC [15]", "Restaurants",
             "Benchmark for dialog state tracking or joint determination of intent and slots. This is similarly a single-domain dataset, but the entities are expressed more in terms of annotations and contain more metadata."]),
            ("MultiWoZ", ["MultiWoZ [16]", "Multidomain",
             "Benchmark for dialog state tracking or joint determination of intent and slots that spans over multiple domains. For the similar reason of variability, modeling this dataset is more challenging than modeling single-domain ones."]),
        ],
        "header": "Dataset Domain Usage",
        "end_prefix": "In addition to these datasets",
    },
}


def _words(text: str) -> str:
    """Whitespace-normalized text with a line-wrap hyphen joined ("sentiment- analysis")."""
    return " ".join(re.sub(r"-\s+", "-", text).split())


def split_row_spec_groups(
    page_rows: list[dict[str, Any]], spec: dict[str, Any], caption_index: int
) -> list[tuple[list[dict[str, Any]], list[str]]]:
    """Return (source rows, field values) for each row of a split-table spec.

    Raises ValueError when the reviewer's field values do not reproduce the
    source text, so a wrong split cannot be written silently.
    """
    texts = [str(row["normalized_text"]) for row in page_rows]
    if spec.get("header"):
        header = next((i for i, text in enumerate(texts) if text == spec["header"]), None)
        if header is None:
            raise ValueError(f"header row not found: {spec['header']}")
    else:
        # Tables without a header row start right after their caption line.
        header = caption_index
    end = next((i for i, text in enumerate(texts) if i > header and text.startswith(spec["end_prefix"])), len(page_rows))
    starts = []
    for marker, _values in spec["rows"]:
        index = next((i for i in range(header + 1, end) if texts[i].startswith(marker)), None)
        if index is None:
            raise ValueError(f"row marker not found: {marker}")
        starts.append(index)
    result: list[tuple[list[dict[str, Any]], list[str]]] = []
    for position, (start, (_marker, values)) in enumerate(zip(starts, spec["rows"], strict=True)):
        stop = starts[position + 1] if position + 1 < len(starts) else end
        source = page_rows[start:stop]
        source_words = _words(" ".join(texts[start:stop]))
        value_words = _words(" ".join(values))
        if source_words != value_words:
            raise ValueError(f"field split does not match source text for row {_marker}")
        result.append((source, values))
    return result


def is_heading(text: str) -> bool:
    words = text.split()
    return len(words) <= 12 and (text.isupper() or bool(HEADING_RE.match(text)))


def looks_like_table(text: str) -> bool:
    return "|" in text or "\t" in text or bool(re.search(r"\S\s{5,}\S", text))


def is_running_footer(line: str) -> bool:
    value = line.strip()
    match = re.match(r"^(\d+)\s*\|\s*Chapter\s+(\d+)\s*:\s*(.+)$", value, re.IGNORECASE)
    if match:
        return True
    match = re.match(r"^(\d+)\s*\|\s*Chapter\s+(\d+)\s+(.+)$", value, re.IGNORECASE)
    if match:
        printed_page, chapter, title = match.groups()
        return int(printed_page) != int(chapter) and "table" not in title.casefold()
    return value.count("|") == 1 and bool(re.match(r"^.+\s\|\s\d+$", value))


def render_lines(lines: list[dict[str, Any]]) -> str:
    """Join lines, removing only an explicit line-wrap hyphen."""
    rendered = ""
    previous_hyphenated = False
    for item in lines:
        text = str(item["normalized_text"]).strip()
        if not text:
            continue
        if not rendered:
            rendered = text
        elif previous_hyphenated and text[:1].islower():
            rendered = rendered[:-1] + text
        else:
            rendered = f"{rendered} {text}"
        previous_hyphenated = text.endswith(HYPHEN_CHARS)
    return rendered


def normal_groups(rows: list[dict[str, Any]], max_chars: int, target_chars: int) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    group: list[dict[str, Any]] = []
    group_text = ""
    for row in rows:
        text = row["normalized_text"]
        if not text:
            group.append(row)
            continue
        special = is_heading(text) or bool(LIST_RE.match(text)) or looks_like_table(text)
        candidate = render_lines([*group, row])
        sentence_boundary = len(group_text) >= target_chars and bool(re.search(r"[.!?][\"'”’)]*$", group_text))
        if group and (special or len(candidate) > max_chars or sentence_boundary):
            groups.append(group)
            group, group_text = [], ""
        group.append(row)
        group_text = render_lines(group)
    if group:
        groups.append(group)
    return groups


def metric_groups(rows: list[dict[str, Any]], max_chars: int) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for row in rows:
        text = row["normalized_text"]
        starts_metric = bool(METRIC_START_RE.match(text)) or bool(
            METRIC_NAME_RE.match(text) and "(" in text
        )
        too_long = bool(current and len(render_lines([*current, row])) > max_chars)
        if current and (starts_metric or too_long):
            groups.append(current)
            current = []
        current.append(row)
    if current:
        groups.append(current)
    return groups


def render_metric_group(lines: list[dict[str, Any]]) -> str:
    """Render one extracted table row with explicit semantic column labels."""
    first = str(lines[0]["normalized_text"])
    match = METRIC_START_RE.match(first)
    if match:
        metric_label = match.group(0)
        metric_name = metric_label.split("[")[0].strip().casefold()
        remainder = first[match.end():].strip()
        content_rows = []
        if remainder:
            content_rows.append({**lines[0], "normalized_text": remainder})
        content_rows.extend(lines[1:])
        content = render_lines(content_rows)
    else:
        combined = render_lines(lines)
        match = METRIC_START_RE.match(combined)
        if not match:
            return combined
        metric_label = match.group(0)
        metric_name = metric_label.split("[")[0].strip().casefold()
        content = combined[match.end():].strip()
        content_rows = []

    application_prefixes = APPLICATION_PREFIXES.get(metric_name, ())
    split_at = next(
        (index for index, row in enumerate(content_rows)
         if any(str(row["normalized_text"]).startswith(prefix) for prefix in application_prefixes)),
        None,
    )
    if split_at is None:
        application_match = next(
            (re.search(rf"(?<!\S){re.escape(prefix)}", content) for prefix in application_prefixes
             if re.search(rf"(?<!\S){re.escape(prefix)}", content)),
            None,
        )
        if application_match:
            description = content[:application_match.start()].strip()
            applications = content[application_match.start():].strip()
        else:
            description, applications = content, ""
    else:
        description = render_lines(content_rows[:split_at])
        applications = render_lines(content_rows[split_at:])

    rendered = [f"Metric: {metric_label}", f"Description: {description}"]
    if applications:
        rendered.append(f"Applications: {applications}")
    return "\n".join(rendered)


def make_chunks(rows: list[dict[str, Any]], max_chars: int, target_chars: int) -> list[dict[str, Any]]:
    """Chunk rows without crossing pages or dropping source line mappings."""
    if max_chars < 1 or target_chars < 1:
        raise ValueError("max_chars and target_chars must be positive")

    by_page: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in rows:
        by_page.setdefault((str(row["document_id"]), int(row["page"])), []).append(row)

    chunks: list[dict[str, Any]] = []
    for (document_id, page), page_rows in sorted(by_page.items()):
        page_rows.sort(key=lambda item: int(item["line"]))
        page_rows = [row for row in page_rows if not is_running_footer(str(row["text"]))]
        if not page_rows:
            continue
        page_rows = [{**row, "normalized_text": str(row["text"]).strip()} for row in page_rows]
        metric_table = False
        table_title, table_spec = next(
            ((title, spec) for title, spec in ROW_SPLIT_SPECS.items()
             if any(str(row["normalized_text"]).startswith(title) for row in page_rows)),
            (None, None),
        )
        groups: list[list[dict[str, Any]]]
        table_line_numbers: set[int] = set()
        rendered_overrides: dict[int, str] = {}

        if table_spec:
            caption_index = next(i for i, row in enumerate(page_rows) if str(row["normalized_text"]).startswith(table_title))
            table_groups = split_row_spec_groups(page_rows, table_spec, caption_index)
            groups = normal_groups(page_rows[:caption_index], max_chars, target_chars)
            if table_spec.get("header"):
                header_index = next(i for i, row in enumerate(page_rows) if str(row["normalized_text"]) == table_spec["header"])
            else:
                header_index = caption_index
            groups.append(page_rows[caption_index:header_index + 1])
            for source_rows, field_values in table_groups:
                groups.append(source_rows)
                rendered_overrides[id(source_rows)] = "\n".join(
                    f"{label}: {value}"
                    for label, value in zip(table_spec["labels"], field_values, strict=True)
                    if value
                )
            end_line = int(table_groups[-1][0][-1]["line"]) if table_groups else int(page_rows[caption_index]["line"])
            tail_rows = [row for row in page_rows if int(row["line"]) > end_line]
            groups += normal_groups(tail_rows, max_chars, target_chars)
            table_line_numbers = {int(row["line"]) for row in page_rows[caption_index:] if int(row["line"]) <= end_line}
        else:
            header_index = next(
                (i for i, row in enumerate(page_rows)
                 if re.match(r"^Metric\s+Description\s+Applications$", row["normalized_text"], re.IGNORECASE)),
                None,
            )
            metric_table = header_index is not None
            if metric_table:
                before_header = page_rows[:header_index]
                after_header = page_rows[header_index:]
                table_rows: list[dict[str, Any]] = []
                tail_rows: list[dict[str, Any]] = []
                in_tail = False
                for row in after_header:
                    if any(row["normalized_text"].startswith(prefix) for prefix in TABLE_EXIT_PREFIXES):
                        in_tail = True
                    (tail_rows if in_tail else table_rows).append(row)
                groups = normal_groups(before_header, max_chars, target_chars)
                groups += metric_groups(table_rows, max_chars)
                groups += normal_groups(tail_rows, max_chars, target_chars)
                table_line_numbers = {int(item["line"]) for item in before_header + table_rows}
            else:
                groups = normal_groups(page_rows, max_chars, target_chars)

        for part in groups:
            if not part:
                continue
            first, last = part[0], part[-1]
            chunks.append({
                "chunk_id": f"{document_id}:p{page}:l{first['line']}-{last['line']}",
                "document_id": document_id,
                "text": rendered_overrides.get(id(part)) or (
                    render_metric_group(part)
                    if metric_table and METRIC_NAME_RE.match(str(part[0]["normalized_text"]))
                    else render_lines(part)
                ),
                "page_start": page,
                "page_end": page,
                "line_start": int(first["line"]),
                "line_end": int(last["line"]),
                "source_line_ids": [f"{document_id}:p{page}:l{int(item['line'])}" for item in part],
                "source_lines": [
                    {"page": page, "line": int(item["line"]), "text": item.get("source_text", item["text"]), "chunk_text": item["normalized_text"]}
                    for item in part
                ],
                "review_flags": ["table_layout_review"] if any(int(item["line"]) in table_line_numbers for item in part) else (["table_like"] if any(looks_like_table(item["text"]) for item in part) else []),
            })
    return chunks
