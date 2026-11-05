# Course Syllabus Q&A Bot

A Python application for question answering over course syllabi with source citations.

## Development setup

Requirements: Python 3.12+ and `uv`.

```powershell
uv sync
uv run pytest -q
uv run ruff check .
uv run uvicorn syllabus_qa.main:app --reload --app-dir src
```

Health check: `http://127.0.0.1:8000/health`.

Secrets belong in a local `.env` file and must not be committed. Do not upload source documents or send them to external services without confirming permission for that use.
