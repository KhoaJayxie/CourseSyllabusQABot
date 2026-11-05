"""Compare Vietnamese and English dense-search queries against one Qdrant collection."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types
from qdrant_client import QdrantClient

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COLLECTION = "practical_nlp_unified"
EMBED_MODEL = "gemini-embedding-001"
VECTOR_SIZE = 768


def embed_query(client: Any, query: str) -> list[float]:
    response = client.models.embed_content(
        model=EMBED_MODEL,
        contents=query,
        config=types.EmbedContentConfig(
            task_type="RETRIEVAL_QUERY",
            output_dimensionality=VECTOR_SIZE,
        ),
    )
    if not response.embeddings or not response.embeddings[0].values:
        raise RuntimeError("Gemini returned an empty query embedding")
    vector = response.embeddings[0].values
    if len(vector) != VECTOR_SIZE:
        raise RuntimeError(f"Expected {VECTOR_SIZE}-dimensional query vector, got {len(vector)}")
    return vector


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--min-score", type=float, default=None)
    parser.add_argument(
        "--query-pair", nargs=2, action="append", metavar=("VI", "EN"),
        help="Vietnamese query and its English equivalent; repeat for multiple pairs.",
    )
    parser.add_argument("--include-toc", action="store_true", help="Include toc chunks; normally skipped because they have no vectors.")
    args = parser.parse_args()
    if args.top_k < 1:
        parser.error("--top-k must be positive")

    pairs = args.query_pair or [
        ("Tokenization là gì?", "What is tokenization?"),
        ("Tài liệu giải thích thế nào về subword tokenization?", "How does the book explain subword tokenization?"),
        ("Mô hình ngôn ngữ là gì?", "What is a language model?"),
    ]
    load_dotenv(ROOT / ".env")
    gemini_key, qdrant_url, qdrant_key = (
        os.getenv("GEMINI_API_KEY"), os.getenv("QDRANT_URL"), os.getenv("QDRANT_API_KEY")
    )
    missing = [name for name, value in (("GEMINI_API_KEY", gemini_key), ("QDRANT_URL", qdrant_url), ("QDRANT_API_KEY", qdrant_key)) if not value]
    if missing:
        print("Missing configuration: " + ", ".join(missing), file=sys.stderr)
        return 2

    gemini = genai.Client(api_key=gemini_key)
    qdrant = QdrantClient(url=qdrant_url, api_key=qdrant_key, timeout=60)
    try:
        collections = {item.name for item in qdrant.get_collections().collections}
        if args.collection not in collections:
            print(f"Collection not found: {args.collection}", file=sys.stderr)
            return 2
        info = qdrant.get_collection(args.collection)
        size = getattr(info.config.params.vectors, "size", None)
        if size != VECTOR_SIZE:
            print(f"Collection vector size is {size}; this script expects {VECTOR_SIZE}.", file=sys.stderr)
            return 2

        for pair_index, (query_vi, query_en) in enumerate(pairs, start=1):
            print(f"\n=== Query pair {pair_index} ===")
            for label, query in (("VI", query_vi), ("EN", query_en)):
                vector = embed_query(gemini, query)
                response = qdrant.query_points(
                    collection_name=args.collection,
                    query=vector,
                    limit=args.top_k,
                    score_threshold=args.min_score,
                    with_payload=True,
                    with_vectors=False,
                )
                print(f"\n[{label}] {query}")
                if not response.points:
                    print("  No matching points.")
                    continue
                for rank, point in enumerate(response.points, start=1):
                    payload = point.payload or {}
                    content = payload.get("content") or {}
                    chunk_type = payload.get("chunk_type", "unknown")
                    if chunk_type == "code":
                        preview = content.get("description") or content.get("symbol") or ""
                    elif chunk_type == "table":
                        preview = content.get("caption") or content.get("table_id") or ""
                    else:
                        preview = content.get("text") or ""
                    preview = " ".join(str(preview).split())
                    if len(preview) > 420:
                        preview = preview[:417] + "..."
                    print(
                        f"  {rank}. score={point.score:.4f} type={chunk_type} "
                        f"pages={payload.get('page_start')}-{payload.get('page_end')} "
                        f"chunk_id={payload.get('chunk_id')}"
                    )
                    print(f"     {preview}")
        return 0
    finally:
        qdrant.close()
        gemini.close()


if __name__ == "__main__":
    raise SystemExit(main())
