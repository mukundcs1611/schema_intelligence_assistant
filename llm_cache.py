"""Exact-match cache for LLM calls that are meant to be deterministic
(temperature=0). Removes redundant network calls for inputs already
classified -- pure cost/latency win, no behavior change, since a cache hit
returns exactly what a fresh call would have returned.

This is Tier 1 of the caching design: exact-match only, safe because the
underlying call is already deterministic. Tier 2 (semantic similarity
cache for the agent's doc-Q&A answers, not yet built) needs a different
mechanism entirely -- "similar" questions aren't "equal" questions, and
reusing an answer across genuinely different questions is a real
correctness risk this tier doesn't have.
"""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "llm_cache.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key TEXT PRIMARY KEY,
    response_json TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL,
    hit_count INTEGER NOT NULL DEFAULT 0
);
"""


def make_cache_key(model: str, **kwargs) -> str:
    """Deterministic key from the exact inputs that shape the prompt --
    sorted so callers don't need to worry about kwarg ordering producing
    different keys for identical input.
    """
    payload = json.dumps({"model": model, **kwargs}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


class LlmCache:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = str(db_path or DEFAULT_DB_PATH)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute(SCHEMA)
        self._conn.commit()

    def get(self, cache_key: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT response_json FROM llm_cache WHERE cache_key = ?", (cache_key,)
        ).fetchone()
        if row is None:
            return None
        self._conn.execute(
            "UPDATE llm_cache SET hit_count = hit_count + 1 WHERE cache_key = ?", (cache_key,)
        )
        self._conn.commit()
        return json.loads(row[0])

    def put(self, cache_key: str, model: str, response: dict) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO llm_cache (cache_key, response_json, model, created_at, hit_count) "
            "VALUES (?, ?, ?, ?, COALESCE((SELECT hit_count FROM llm_cache WHERE cache_key = ?), 0))",
            (
                cache_key, json.dumps(response), model,
                datetime.now(timezone.utc).isoformat(timespec="seconds"), cache_key,
            ),
        )
        self._conn.commit()

    def stats(self) -> dict:
        row = self._conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(hit_count), 0) FROM llm_cache"
        ).fetchone()
        return {"cached_entries": row[0], "cache_hits": row[1]}

    def close(self) -> None:
        self._conn.close()
