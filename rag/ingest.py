"""Layer 1 of the RAG pipeline: parse rag/corpus/*.md into chunks, embed them,
build a BM25 index, and persist both to rag/index/ for retrieve.py to load.

This is a one-shot offline script -- run it whenever the corpus changes, not
per query. See rag/retrieve.py for the query-time half of the pipeline.

Design notes:
  - Chunk boundary: H3 heading (Usage / Parameters / Examples). Docs with no
    H3s (the 4 non-function docs) chunk at H2 instead.
  - chunk_id / documentation_reference: "<file>.md#<h2-slug>-<h3-slug>",
    or "<file>.md#<h2-slug>" when there's no H3. Combining H2+H3 avoids the
    anchor collision that a naive H3-only slug would hit in the three
    multi-function docs (phone_ssn_mask.md, credit_card_account_mask.md,
    address_ip_national_id_mask.md), which each have >1 section reusing the
    same H3 headings (Usage/Parameters/Examples) under different H2s.
  - pii_category: resolved from the nearest H2 ancestor via
    FUNCTION_HEADING_TO_CATEGORY below, not inferred by an LLM. None for
    chunks under non-function docs.
"""
import json
import pickle
import re
from pathlib import Path

import numpy as np
import ollama
from rank_bm25 import BM25Okapi

CORPUS_DIR = Path(__file__).resolve().parent / "corpus"
INDEX_DIR = Path(__file__).resolve().parent / "index"
EMBED_MODEL = "nomic-embed-text"

# H2 heading text (as it appears in the corpus, uppercase function name) ->
# pii_category. Matches pii-detector/pii_patterns.py's MASKING_FUNCTION_MAP
# keys, just inverted (function name -> category instead of category ->
# function). Docs/headings not listed here (overview, config, compliance,
# troubleshooting, performance) resolve to None.
FUNCTION_HEADING_TO_CATEGORY = {
    "NAME_RANDOMIZE": "FULL_NAME",
    "EMAIL_MASK": "EMAIL",
    "PHONE_MASK": "PHONE",
    "SSN_MASK": "SSN",
    "CREDIT_CARD_MASK": "CREDIT_CARD",
    "ACCOUNT_MASK": "ACCOUNT_NUMBER",
    "DATE_SHIFT": "DATE_OF_BIRTH",
    "ADDRESS_RANDOMIZE": "ADDRESS",
    "IP_MASK": "IP_ADDRESS",
    "NATIONAL_ID_MASK": "NATIONAL_ID",
}

_H1_RE = re.compile(r"^#\s+(.*)")
_H2_RE = re.compile(r"^##\s+(.*)")
_H3_RE = re.compile(r"^###\s+(.*)")


def slugify(heading_text: str) -> str:
    """'PHONE_MASK' -> 'phone_mask', 'Usage' -> 'usage'."""
    slug = re.sub(r"[^a-z0-9]+", "_", heading_text.strip().lower())
    return slug.strip("_")


def tokenize_for_bm25(text: str) -> list[str]:
    """Shared word tokenizer -- retrieve.py must use this exact function to
    tokenize queries, or BM25 scores become meaningless (index built on one
    tokenization, queried with another).
    """
    return re.findall(r"[a-z0-9]+", text.lower())


def assign_pii_category(h2_heading: str | None) -> str | None:
    if h2_heading is None:
        return None
    return FUNCTION_HEADING_TO_CATEGORY.get(h2_heading)


def parse_markdown_into_chunks(filepath: Path) -> list[dict]:
    """Walk one corpus markdown file and return a list of chunk records.
    Chunks at H3 boundaries where H3s exist under an H2; falls back to H2
    boundaries for docs with no H3 sectioning at all (the 4 non-function
    docs). See module docstring for the anchor-collision reasoning.
    """
    source_file = filepath.name
    lines = filepath.read_text().splitlines()

    doc_title = None
    current_h2 = None
    current_h3 = None
    buffer: list[str] = []
    chunks: list[dict] = []

    def flush():
        text = "\n".join(buffer).strip()
        buffer.clear()
        if not text or current_h2 is None:
            return
        h2_slug = slugify(current_h2)
        if current_h3:
            chunk_id = f"{source_file}#{h2_slug}-{slugify(current_h3)}"
        else:
            chunk_id = f"{source_file}#{h2_slug}"
        chunks.append({
            "chunk_id": chunk_id,
            "doc_title": doc_title,
            "source_file": source_file,
            "h2_heading": current_h2,
            "h3_heading": current_h3,
            "text": text,
            "pii_category": assign_pii_category(current_h2),
        })

    for line in lines:
        h3_match = _H3_RE.match(line)
        h2_match = _H2_RE.match(line)
        h1_match = _H1_RE.match(line)
        if h3_match:
            flush()
            current_h3 = h3_match.group(1).strip()
        elif h2_match:
            flush()
            current_h2 = h2_match.group(1).strip()
            current_h3 = None
        elif h1_match:
            doc_title = h1_match.group(1).strip()
        else:
            buffer.append(line)
    flush()
    return chunks


def embed_chunks(chunks: list[dict]) -> np.ndarray:
    """Embed every chunk's text with EMBED_MODEL via Ollama. Returns an
    (n_chunks, embedding_dim) array, row i corresponding to chunks[i] --
    retrieve.py relies on this index alignment.
    """
    vectors = [ollama.embeddings(model=EMBED_MODEL, prompt=c["text"])["embedding"] for c in chunks]
    return np.array(vectors, dtype=np.float32)


def build_bm25_index(chunks: list[dict]) -> BM25Okapi:
    tokenized = [tokenize_for_bm25(c["text"]) for c in chunks]
    return BM25Okapi(tokenized)


def run_ingestion(corpus_dir: Path = CORPUS_DIR, index_dir: Path = INDEX_DIR) -> None:
    chunks: list[dict] = []
    for filepath in sorted(corpus_dir.glob("*.md")):
        chunks.extend(parse_markdown_into_chunks(filepath))

    if not chunks:
        raise ValueError(f"No chunks parsed from {corpus_dir} -- check the corpus exists and has headings.")

    embeddings = embed_chunks(chunks)
    bm25 = build_bm25_index(chunks)

    index_dir.mkdir(exist_ok=True)
    (index_dir / "chunks.json").write_text(json.dumps(chunks, indent=2))
    np.save(index_dir / "embeddings.npy", embeddings)
    with open(index_dir / "bm25_index.pkl", "wb") as f:
        pickle.dump(bm25, f)

    print(f"Ingested {len(chunks)} chunks from {len(list(corpus_dir.glob('*.md')))} documents -> {index_dir}")


if __name__ == "__main__":
    run_ingestion()
