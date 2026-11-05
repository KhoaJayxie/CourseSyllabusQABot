from syllabus_qa.ingest.chunker import make_chunks


def row(page: int, line: int, text: str) -> dict[str, object]:
    return {
        "document_id": "test-doc",
        "page": page,
        "line": line,
        "text": text,
        "source_text": text,
    }


def test_wrap_hyphen_joins_once_and_keeps_both_source_lines() -> None:
    chunks = make_chunks(
        [row(1, 1, "The docu‐"), row(1, 2, "ments are searchable.")],
        max_chars=100,
        target_chars=80,
    )

    assert len(chunks) == 1
    assert chunks[0]["text"] == "The documents are searchable."
    assert [line["line"] for line in chunks[0]["source_lines"]] == [1, 2]
    assert chunks[0]["source_lines"][0]["text"] == "The docu‐"
    assert chunks[0]["source_lines"][1]["text"] == "ments are searchable."


def test_intermediate_wrapped_line_is_not_lost() -> None:
    chunks = make_chunks(
        [
            row(1, 1, "representing docu‐"),
            row(1, 2, "ments to new"),
            row(1, 3, "applications continued."),
        ],
        max_chars=200,
        target_chars=180,
    )

    assert "representing documents to new applications continued." in chunks[0]["text"]
    assert [line["line"] for line in chunks[0]["source_lines"]] == [1, 2, 3]


def test_question_mark_is_not_guessed_as_hyphen() -> None:
    chunks = make_chunks([row(1, 1, "docu?"), row(1, 2, "ments")], 100, 80)
    assert chunks[0]["text"] == "docu? ments"


def test_footer_is_removed_but_table_caption_is_preserved() -> None:
    chunks = make_chunks(
        [row(1, 1, "70 | Chapter 2: NLP Pipeline"), row(1, 2, "Table 2-2. Popular metrics and NLP applications")],
        1000,
        800,
    )
    assert len(chunks) == 1
    assert chunks[0]["text"] == "Table 2-2. Popular metrics and NLP applications"
    assert [line["line"] for line in chunks[0]["source_lines"]] == [2]


    chunks = make_chunks(
        [
            row(1, 1, "A docu?"),
            row(1, 2, "ment is uncertain."),
            row(2, 1, "A docu‐"),
            row(2, 2, "ment is split."),
        ],
        max_chars=100,
        target_chars=80,
    )

    assert chunks[0]["text"] == "A docu? ment is uncertain."
    assert chunks[1]["text"] == "A document is split."


def test_table_layout_page_is_flagged_for_review() -> None:
    chunks = make_chunks(
        [row(1, 1, "Metric Description Applications"), row(1, 2, "ROUGE [55] Description here")],
        max_chars=100,
        target_chars=80,
    )

    assert all("table_layout_review" in chunk["review_flags"] for chunk in chunks)


def test_metric_table_groups_wrapped_rows_by_metric() -> None:
    chunks = make_chunks(
        [
            row(100, 1, "Metric Description Applications"),
            row(100, 2, "ROUGE [55] Another metric description"),
            row(100, 3, "with a wrapped continuation."),
            row(100, 4, "recall."),
            row(100, 5, "Perplexity [56] A probabilistic metric."),
            row(100, 6, "Used to evaluate language models."),
        ],
        max_chars=1800,
        target_chars=1000,
    )

    assert [chunk["line_start"] for chunk in chunks] == [1, 2, 5]
    assert "Metric: ROUGE [55]" in chunks[1]["text"]
    assert "Description: Another metric description with a wrapped continuation. recall." in chunks[1]["text"]
    assert "Applications: Used to evaluate language models." in chunks[2]["text"]
    assert all("table_layout_review" in chunk["review_flags"] for chunk in chunks)
    assert sum(len(chunk["source_lines"]) for chunk in chunks) == 6


def test_paragraph_after_table_is_separate_from_metrics() -> None:
    chunks = make_chunks(
        [
            row(100, 1, "Table 2-2. Popular metrics"),
            row(100, 2, "Metric Description Applications"),
            row(100, 3, "ROUGE [55] Description row."),
            row(100, 4, "Perplexity [56] Description row."),
            row(100, 5, "Apart from the list of metrics shown in Table 2-2, more text."),
            row(100, 6, "This paragraph continues here."),
        ],
        1800,
        1000,
    )
    metric_chunk = next(chunk for chunk in chunks if "ROUGE" in chunk["text"])
    tail_chunk = next(chunk for chunk in chunks if "Apart from the list" in chunk["text"])
    assert "Perplexity" not in metric_chunk["text"]
    assert "Apart from the list" not in metric_chunk["text"]
    assert "This paragraph continues" in tail_chunk["text"]
    assert "table_layout_review" not in tail_chunk["review_flags"]


def test_page_boundary_is_never_crossed() -> None:
    chunks = make_chunks([row(1, 1, "First page."), row(2, 1, "Second page.")], 100, 80)

    assert len(chunks) == 2
    assert [chunk["page_start"] for chunk in chunks] == [1, 2]

