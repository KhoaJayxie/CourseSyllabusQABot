"""Embed unified JSONL chunks with Gemini and upsert them into Qdrant.

This script never deletes a collection or points. Re-running it upserts the same
stable point IDs, making ingestion idempotent for a given source file/model.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types
from qdrant_client import QdrantClient, models

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "data" / "qdrant" / "practical_nlp.unified.chunks.jsonl"
DEFAULT_COLLECTION = "practical_nlp_unified"
EMBED_MODEL = "gemini-embedding-001"
VECTOR_SIZE = 768
POINT_NAMESPACE = uuid.UUID("5fd334df-08e6-4c7c-9b5a-0b6d8b85ee8e")


def read_chunks(path: Path) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            chunk = json.loads(line)
            chunk_id = chunk.get("chunk_id")
            if not isinstance(chunk_id, str) or not chunk_id:
                raise ValueError(f"Missing chunk_id at JSONL line {line_number}")
            if chunk_id in seen:
                raise ValueError(f"Duplicate chunk_id: {chunk_id}")
            seen.add(chunk_id)
            if not isinstance(chunk.get("embed_text"), str):
                raise TypeError(f"embed_text must be a string for {chunk_id}")
            chunks.append(chunk)
    if not chunks:
        raise ValueError(f"No chunks found in {path}")
    return chunks


def point_uuid(chunk_id: str) -> str:
    return str(uuid.uuid5(POINT_NAMESPACE, chunk_id))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")

    load_dotenv(ROOT / ".env")
    gemini_key = os.getenv("GEMINI_API_KEY")
    qdrant_url = os.getenv("QDRANT_URL")
    qdrant_key = os.getenv("QDRANT_API_KEY")
    missing = [name for name, value in (
        ("GEMINI_API_KEY", gemini_key),
        ("QDRANT_URL", qdrant_url),
        ("QDRANT_API_KEY", qdrant_key),
    ) if not value]
    if missing:
        print("Missing configuration: " + ", ".join(missing), file=sys.stderr)
        return 2
    if not args.source.is_file():
        print(f"Source file not found: {args.source}", file=sys.stderr)
        return 2

    chunks = read_chunks(args.source)
    embedded = [chunk for chunk in chunks if chunk["embed_text"].strip()]
    skipped_empty = len(chunks) - len(embedded)
    gemini = genai.Client(api_key=gemini_key)
    client = QdrantClient(url=qdrant_url, api_key=qdrant_key, timeout=60)

    try:
        existing = {item.name for item in client.get_collections().collections}
        if args.collection not in existing:
            client.create_collection(
                collection_name=args.collection,
                vectors_config=models.VectorParams(size=VECTOR_SIZE, distance=models.Distance.COSINE),
            )
            print(f"Created collection: {args.collection} (dimension={VECTOR_SIZE}, cosine)")
        else:
            info = client.get_collection(args.collection)
            vector_config = info.config.params.vectors
            existing_size = getattr(vector_config, "size", None)
            if existing_size != VECTOR_SIZE:
                raise ValueError(
                    f"Collection {args.collection!r} has vector size {existing_size}; "
                    f"expected {VECTOR_SIZE}. No points were written."
                )
            print(f"Using existing collection: {args.collection} (dimension={existing_size})")

        written = 0
        for start in range(0, len(embedded), args.batch_size):
            batch = embedded[start:start + args.batch_size]
            response = gemini.models.embed_content(
                model=EMBED_MODEL,
                contents=[chunk["embed_text"] for chunk in batch],
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_DOCUMENT",
                    output_dimensionality=VECTOR_SIZE,
                ),
            )
            vectors = response.embeddings or []
            if len(vectors) != len(batch):
                raise RuntimeError(
                    f"Gemini returned {len(vectors)} embeddings for {len(batch)} chunks; "
                    "stopping before this batch is written."
                )
            points = []
            for chunk, embedding in zip(batch, vectors, strict=True):
                values = embedding.values
                if not values or len(values) != VECTOR_SIZE:
                    raise RuntimeError(f"Unexpected embedding size for {chunk['chunk_id']}")
                payload = {key: value for key, value in chunk.items() if key != "embed_text"}
                payload["embedding_model"] = EMBED_MODEL
                payload["embedding_dimensions"] = VECTOR_SIZE
                points.append(models.PointStruct(
                    id=point_uuid(chunk["chunk_id"]),
                    vector=values,
                    payload=payload,
                ))
            client.upsert(collection_name=args.collection, points=points, wait=True)
            written += len(points)
            print(f"Upserted {written}/{len(embedded)} embedded chunks")
            if args.sleep_seconds:
                time.sleep(args.sleep_seconds)

        info = client.get_collection(args.collection)
        print(f"Ingestion complete: collection={args.collection}")
        print(f"Source chunks: {len(chunks)}; points upserted: {written}; empty embed_text skipped: {skipped_empty}")
        print(f"Collection point count: {info.points_count}")
        print(f"Embedding model: {EMBED_MODEL}; vector size: {VECTOR_SIZE}")
        return 0
    finally:
        client.close()
        gemini.close()


if __name__ == "__main__":
    raise SystemExit(main())
