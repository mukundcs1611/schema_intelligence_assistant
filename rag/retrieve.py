"""Layer 2 of the RAG pipeline: query-time hybrid retrieval over the index
rag/ingest.py built. Loads chunks.json / embeddings.npy / bm25_index.pkl
once (cached), then for each query:

  1. vector_search  -- cosine similarity, ranked
  2. bm25_search    -- BM25 keyword score, ranked
  3. reciprocal_rank_fusion(k=60) over both rankings
  4. pii_category_filter applied AFTER fusion, not before -- filtering the
     candidate pool pre-ranking would let a query win by elimination rather
     than by actually ranking correctly among all categories.
"""
import functools
import json
import pickle
from pathlib import Path

import numpy as np
import ollama

from ingest import EMBED_MODEL, tokenize_for_bm25

INDEX_DIR = Path(__file__).resolve().parent / "index"
RRF_K = 60
CANDIDATE_POOL_SIZE = 10  # top_n pulled from each of vector/BM25 before fusion


@functools.lru_cache(maxsize=1)
def load_index(index_dir: Path = INDEX_DIR):
    """Cached -- re-run rag/ingest.py and restart the process to pick up a
    changed corpus; this cache does not watch the files for changes.
    """
    chunks = json.loads((index_dir / "chunks.json").read_text())
    embeddings = np.load(index_dir / "embeddings.npy")
    with open(index_dir / "bm25_index.pkl", "rb") as f:
        bm25 = pickle.load(f)
    return chunks, embeddings, bm25


def vector_search(query: str, chunks: list[dict], embeddings: np.ndarray, top_n: int = CANDIDATE_POOL_SIZE) -> list[tuple[int, float]]:
    """Returns [(chunk_idx, cosine_similarity), ...] ranked descending."""
    query_vec = np.array(ollama.embeddings(model=EMBED_MODEL, prompt=query)["embedding"], dtype=np.float32)
    doc_norms = np.linalg.norm(embeddings, axis=1)
    query_norm = np.linalg.norm(query_vec)
    denom = doc_norms * query_norm
    denom[denom == 0] = 1e-10
    similarities = (embeddings @ query_vec) / denom
    top_idx = np.argsort(-similarities)[:top_n]
    return [(int(i), float(similarities[i])) for i in top_idx]


def bm25_search(query: str, chunks: list[dict], bm25, top_n: int = CANDIDATE_POOL_SIZE) -> list[tuple[int, float]]:
    """Returns [(chunk_idx, bm25_score), ...] ranked descending."""
    scores = bm25.get_scores(tokenize_for_bm25(query))
    top_idx = np.argsort(-scores)[:top_n]
    return [(int(i), float(scores[i])) for i in top_idx]


def reciprocal_rank_fusion(rankings: list[list[tuple[int, float]]], k: int = RRF_K) -> list[tuple[int, float]]:
    """rankings: one ranked (idx, raw_score) list per retrieval method. The
    raw scores are discarded here -- only rank position is used, which is
    the entire point of RRF (it works across incomparable score scales).
    Returns [(chunk_idx, fused_score), ...] sorted descending.
    """
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, (idx, _score) in enumerate(ranking, start=1):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + rank)
    return sorted(fused.items(), key=lambda pair: pair[1], reverse=True)


def retrieve(query: str, pii_category_filter: str | None = None, top_k: int = 3, index_dir: Path = INDEX_DIR) -> list[dict]:
    chunks, embeddings, bm25 = load_index(index_dir)

    vec_ranked = vector_search(query, chunks, embeddings)
    bm25_ranked = bm25_search(query, chunks, bm25)
    fused = reciprocal_rank_fusion([vec_ranked, bm25_ranked])

    if pii_category_filter is not None:
        fused = [(idx, score) for idx, score in fused if chunks[idx]["pii_category"] == pii_category_filter]

    results = []
    for idx, score in fused[:top_k]:
        chunk = dict(chunks[idx])
        chunk["retrieval_score"] = score
        results.append(chunk)
    return results


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "how to mask email addresses"
    for r in retrieve(q):
        print(f"{r['retrieval_score']:.4f}  {r['chunk_id']}")
