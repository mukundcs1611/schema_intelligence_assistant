# Scalability

## 1. Detection at 5,000 columns, under 30 seconds

LLM calls are the only meaningful cost. Three mechanisms, by impact:

**Layer 1 is free.** Keyword, regex and checksum matching, no inference.
Measured: 70% of the golden set resolves with no LLM call
(`eval_report.md`); 5,000 rule evaluations take ~2 seconds.

**Exact-match cache.** Layer 2 runs at `temperature=0`, so identical column
descriptors are served from `llm_cache.db`. Repeat scans — the weekly
pattern — mostly skip inference; our detector suite drops from ~24s to under
1s warm.

**Parallelism — not yet built.** The remaining ~1,500 escalated columns are
processed sequentially today. They are I/O-bound on Ollama, so a thread pool
over just that fraction is the next step: at 8 concurrent requests and ~250
tokens per column, roughly 25 seconds. A projection, not a measurement —
the target is currently unmet for a cold 5,000-column schema.

## 2. RAG freshness

Treat the corpus as the product documentation repository, not a copy. A
post-merge webhook re-runs `rag/ingest.py`. Chunk IDs derive from file plus
heading, so re-ingestion is idempotent — a changed document replaces its own
chunks rather than duplicating them. New masking functions become queryable
in the cycle they ship, no PS involvement. Cached
documentation answers must be invalidated on re-ingest: a cached answer is
only valid against the corpus version that produced it.

## 3. Cost at 500 customers, analysing weekly

```
500 customers × 200 columns × 30% escalation = 30,000 LLM calls/week
× ~250 tokens                                ≈ 30M tokens/month
```

Self-hosted Ollama has no marginal token cost; the expense is one inference
server. On a cloud small-model tier (~$0.20/1M) the same volume is ~$6/month.
Infrastructure dominates, not tokens. Caching cuts it further where
customers share standard ERP naming.

## 4. Quality monitoring in production

| Metric | Alert threshold | Action |
|---|---|---|
| Auto-configuration rate | < 70% | Confidence miscalibrated for this schema type |
| Review-queue acceptance | < 60% over 7 days | Suggestions degrading — check prompt/model drift |
| Golden-set recall | < 0.90 | Roll back the last rule change |
| Layer 2 p95 latency | > 5s per column | Ollama queue saturated |
| Audit log write failure | any | Silent data loss — halt immediately |

All are SQLite queries over `audit_log.db`, computed nightly. v1 needs no
external monitoring stack; the audit schema exports to a central
platform unchanged.
