"""FastAPI application entry point."""
from fastapi import FastAPI

app = FastAPI(title="Course Syllabus Q&A Bot", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    """Return a minimal health status without exposing secrets."""
    return {"status": "ok"}
