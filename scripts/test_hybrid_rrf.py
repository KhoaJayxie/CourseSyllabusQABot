"""Compare dense, BM25, RRF, and Jina reranking for user queries."""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types
from qdrant_client import QdrantClient

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "data" / "qdrant" / "practical_nlp.unified.chunks.jsonl"
DEFAULT_COLLECTION = "practical_nlp_unified"
EMBED_MODEL = "gemini-embedding-001"
RERANK_MODEL = "jina-reranker-v3.5"
RERANK_URL = "https://api.jina.ai/v1/rerank"
VECTOR_SIZE = 768
TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)


def tokens(text: str) -> list[str]:
    return [match.group(0).casefold() for match in TOKEN_RE.finditer(text)]


def bm25_text(chunk: dict[str, Any]) -> str:
    """Use retrieval text, plus table/caption and code description metadata."""
    parts = [str(chunk.get("embed_text", ""))]
    content = chunk.get("content") or {}
    for key in ("caption", "context", "description", "symbol", "table_id"):
        if content.get(key):
            parts.append(str(content[key]))
    return " ".join(parts)


class BM25:
    def __init__(self, documents: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.lengths = [len(doc) for doc in documents]
        self.avg_length = sum(self.lengths) / max(1, len(self.lengths))
        self.term_freqs = [Counter(doc) for doc in documents]
        self.doc_freqs: Counter[str] = Counter()
        for freq in self.term_freqs:
            self.doc_freqs.update(freq.keys())
        self.count, self.k1, self.b = len(documents), k1, b

    def search(self, query: str, limit: int) -> list[tuple[int, float]]:
        scores: list[tuple[int, float]] = []
        for index, freqs in enumerate(self.term_freqs):
            score = 0.0
            doc_len = self.lengths[index]
            for term in tokens(query):
                tf = freqs.get(term, 0)
                if tf:
                    df = self.doc_freqs[term]
                    idf = math.log(1 + (self.count - df + 0.5) / (df + 0.5))
                    denom = tf + self.k1 * (1 - self.b + self.b * doc_len / max(self.avg_length, 1))
                    score += idf * tf * (self.k1 + 1) / denom
            if score > 0:
                scores.append((index, score))
        return sorted(scores, key=lambda pair: (-pair[1], pair[0]))[:limit]


def embed_query(client: Any, query: str) -> list[float]:
    response = client.models.embed_content(
        model=EMBED_MODEL,
        contents=query,
        config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY", output_dimensionality=VECTOR_SIZE),
    )
    if not response.embeddings or not response.embeddings[0].values:
        raise RuntimeError("Gemini returned an empty query embedding")
    vector = response.embeddings[0].values
    if len(vector) != VECTOR_SIZE:
        raise RuntimeError(f"Expected {VECTOR_SIZE}-dimensional vector, got {len(vector)}")
    return vector


def rerank_jina(api_key: str, query: str, candidates: list[dict[str, Any]], top_n: int) -> list[tuple[dict[str, Any], float]]:
    documents = [bm25_text(chunk) for chunk in candidates]
    request_body = json.dumps({
        "model": RERANK_MODEL,
        "query": query,
        "documents": documents,
        "top_n": min(top_n, len(documents)),
    }).encode("utf-8")
    request = urllib.request.Request(
        RERANK_URL,
        data=request_body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"Jina rerank request failed (HTTP {exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach Jina rerank API: {exc.reason}") from exc
    results = payload.get("results")
    if not isinstance(results, list):
        raise TypeError("Jina response did not include a results array")
    output = []
    for item in results:
        index = int(item["index"])
        if index < 0 or index >= len(candidates):
            raise RuntimeError(f"Jina returned invalid document index: {index}")
        output.append((candidates[index], float(item["relevance_score"])))
    return output


def preview(chunk: dict[str, Any]) -> str:
    content = chunk.get("content") or {}
    kind = chunk.get("chunk_type", "unknown")
    if kind == "code":
        value = content.get("description") or content.get("symbol") or ""
    elif kind == "table":
        value = content.get("caption") or content.get("table_id") or ""
    else:
        value = content.get("text") or ""
    value = " ".join(str(value).split())
    return value if len(value) <= 350 else value[:347] + "..."


def print_result(rank: int, chunk: dict[str, Any], score: float, label: str) -> None:
    print(
        f"  {rank}. {label}={score:.4f} type={chunk.get('chunk_type')} "
        f"pages={chunk.get('page_start')}-{chunk.get('page_end')} id={chunk.get('chunk_id')}"
    )
    print(f"     {preview(chunk)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--dense-k", type=int, default=20, help="Dense Qdrant candidates; default 20")
    parser.add_argument("--bm25-k", type=int, default=20, help="BM25 lexical candidates; default 20")
    parser.add_argument("--rrf-top-k", type=int, default=10, help="Fused candidates sent to Jina; default 10")
    parser.add_argument("--rerank-top-k", type=int, default=3, help="Final Jina results; default 3")
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--query-pair", nargs=2, action="append", metavar=("VI", "EN"))
    parser.add_argument("--query", action="append", help="Run one query; may repeat.")
    args = parser.parse_args()
    if min(args.dense_k, args.bm25_k, args.rrf_top_k, args.rerank_top_k, args.rrf_k) < 1:
        parser.error("All top-k and rrf-k values must be positive")
    if args.rerank_top_k > args.rrf_top_k:
        parser.error("--rerank-top-k cannot exceed --rrf-top-k")
    if not args.source.is_file():
        parser.error(f"Source JSONL not found: {args.source}")

    with args.source.open(encoding="utf-8") as stream:
        chunks = [json.loads(line) for line in stream if line.strip()]
    chunks = [chunk for chunk in chunks if str(chunk.get("embed_text", "")).strip()]
    if not chunks:
        print("No chunks with non-empty embed_text.", file=sys.stderr)
        return 2
    bm25 = BM25([tokens(bm25_text(chunk)) for chunk in chunks])

    queries: list[tuple[str, str]] = []
    for index, (vi, en) in enumerate(args.query_pair or [], start=1):
        queries.extend([(f"Pair {index} VI", vi), (f"Pair {index} EN", en)])
    queries.extend((f"Query {i}", query) for i, query in enumerate(args.query or [], start=1))
    if not queries:
        queries = [("VI", "Tokenization là gì?"), ("EN", "What is tokenization?")]

    load_dotenv(ROOT / ".env")
    gemini_key, qdrant_url, qdrant_key, jina_key = (
        os.getenv("GEMINI_API_KEY"), os.getenv("QDRANT_URL"), os.getenv("QDRANT_API_KEY"), os.getenv("JINA_API_KEY")
    )
    missing = [name for name, value in (("GEMINI_API_KEY", gemini_key), ("QDRANT_URL", qdrant_url), ("QDRANT_API_KEY", qdrant_key), ("JINA_API_KEY", jina_key)) if not value]
    if missing:
        print("Missing configuration: " + ", ".join(missing), file=sys.stderr)
        return 2

    gemini = genai.Client(api_key=gemini_key)
    qdrant = QdrantClient(url=qdrant_url, api_key=qdrant_key, timeout=60)
    try:
        names = {entry.name for entry in qdrant.get_collections().collections}
        if args.collection not in names:
            print(f"Collection not found: {args.collection}", file=sys.stderr)
            return 2
        info = qdrant.get_collection(args.collection)
        size = getattr(info.config.params.vectors, "size", None)
        if size != VECTOR_SIZE:
            print(f"Collection vector size {size} does not match expected {VECTOR_SIZE}.", file=sys.stderr)
            return 2

        for label, query in queries:
            vector = embed_query(gemini, query)
            dense_resp = qdrant.query_points(
                collection_name=args.collection, query=vector, limit=args.dense_k,
                with_payload=True, with_vectors=False,
            )
            dense = [dict(point.payload or {}) for point in dense_resp.points]
            dense_rank = {row["chunk_id"]: rank for rank, row in enumerate(dense, start=1)}

            lexical = [(chunks[index], score) for index, score in bm25.search(query, args.bm25_k)]
            lexical_rank = {row["chunk_id"]: rank for rank, (row, _score) in enumerate(lexical, start=1)}
            lexical_map = {row["chunk_id"]: row for row, _score in lexical}

            scores: dict[str, float] = {}
            for chunk_id in set(dense_rank) | set(lexical_rank):
                scores[chunk_id] = (
                    (1 / (args.rrf_k + dense_rank[chunk_id]) if chunk_id in dense_rank else 0)
                    + (1 / (args.rrf_k + lexical_rank[chunk_id]) if chunk_id in lexical_rank else 0)
                )
            by_id = {row["chunk_id"]: row for row in dense}
            by_id.update(lexical_map)
            fused_ids = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))[:args.rrf_top_k]
            fused_candidates = [by_id[chunk_id] for chunk_id in fused_ids]

            print(f"\n=== {label}: {query} ===")
            print(f"Dense candidates: top {args.dense_k}; BM25 candidates: top {args.bm25_k}")
            print(f"RRF fused candidates: top {len(fused_candidates)} (k={args.rrf_k})")
            for rank, chunk_id in enumerate(fused_ids, start=1):
                print_result(rank, by_id[chunk_id], scores[chunk_id], "rrf")

            reranked = rerank_jina(jina_key, query, fused_candidates, args.rerank_top_k)
            print(f"Jina {RERANK_MODEL}: top {len(reranked)} from RRF candidates")
            for rank, (chunk, score) in enumerate(reranked, start=1):
                print_result(rank, chunk, score, "jina")
        return 0
    finally:
        qdrant.close()
        gemini.close()


if __name__ == "__main__":
    raise SystemExit(main())
