"""Local provider smoke test; never prints credentials or document content."""
from __future__ import annotations

import os
import sys
from uuid import uuid4

from dotenv import load_dotenv
from google import genai
from google.genai import types
from qdrant_client import QdrantClient, models


def main() -> int:
    load_dotenv()
    gemini_key = os.getenv("GEMINI_API_KEY")
    qdrant_url = os.getenv("QDRANT_URL")
    qdrant_key = os.getenv("QDRANT_API_KEY")
    missing = [name for name, value in (
        ("GEMINI_API_KEY", gemini_key),
        ("QDRANT_URL", qdrant_url),
        ("QDRANT_API_KEY", qdrant_key),
    ) if not value]
    if missing:
        print("Missing configuration: " + ", ".join(missing))
        return 2

    # This smoke test uses a generic test phrase, not the user's PDF.
    try:
        gemini = genai.Client(api_key=gemini_key)
        response = gemini.models.embed_content(
            model="gemini-embedding-001",
            contents="A generic course syllabus smoke test.",
            config=types.EmbedContentConfig(output_dimensionality=768),
        )
        if not response.embeddings or not response.embeddings[0].values:
            raise RuntimeError("Gemini returned no embedding")
        dimension = len(response.embeddings[0].values)
        print(f"Gemini embedding OK (dimension={dimension})")
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"Gemini smoke test failed: {type(exc).__name__}: {exc}")
        return 1

    client = None
    collection = f"smoke_{uuid4().hex[:12]}"
    try:
        client = QdrantClient(url=qdrant_url, api_key=qdrant_key, timeout=20)
        client.create_collection(
            collection_name=collection,
            vectors_config=models.VectorParams(size=dimension, distance=models.Distance.COSINE),
        )
        info = client.get_collection(collection)
        print(f"Qdrant test collection OK (vector size={info.config.params.vectors.size})")
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"Qdrant smoke test failed: {type(exc).__name__}: {exc}")
        return 1
    finally:
        if client is not None:
            try:
                client.delete_collection(collection)
                print("Temporary Qdrant test collection deleted")
            except (RuntimeError, ValueError, OSError) as exc:
                print(f"Could not clean up temporary collection: {type(exc).__name__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
