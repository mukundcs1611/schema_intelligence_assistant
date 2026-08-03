Implementation: Python

# Schema Intelligence Assistant

Analyses a database schema, identifies which columns contain PII, generates a
masking configuration for them, and answers questions about masking
documentation — targeting the onboarding bottleneck where a professional
services team spends 3–4 days per customer reviewing schemas by hand.

Runs entirely on local models (Ollama). No API keys, no external calls.

---

## Architecture

```
                    ┌────────────────────────────────┐
                    │  User (agent REPL / library)   │
                    └───────────────┬────────────────┘
                                    │  message
                                    ▼
   ┌────────────────────────────────────────────────────────────────┐
   │  agent/agent.py                                                │
   │                                                                │
   │  1. Deterministic parse   schema JSON? "column X in table Y"?  │
   │                           "generate masking config"?           │
   │     ── resolves most requests with no LLM call at all ──       │
   │                                                                │
   │  2. Ollama native tool-calling (qwen2.5:7b, temperature=0)     │
   │     chooses the tool for what's left; its ARGUMENTS are        │
   │     discarded — only the selection is used  (see decision 3)   │
   │                                                                │
   │  3. No tool selected → refuse (out of scope) or ask for data   │
   └───────┬─────────────────────┬──────────────────────┬───────────┘
           │                     │                      │
           ▼                     ▼                      ▼
  ┌─────────────────┐  ┌──────────────────┐  ┌────────────────────┐
  │ pii-detector/   │  │ masking-         │  │ rag/retrieve.py    │
  │   detector.py   │  │  generator/      │  │                    │
  │                 │  │   generator.py   │  │ vector (nomic-     │
  │ L1 rule engine  │  │                  │  │  embed-text)       │
  │  keywords+regex │  │ DetectionResult[]│  │      +             │
  │  +Luhn checksum │  │        ↓         │  │ BM25 (rank_bm25)   │
  │  ~70% resolve   │  │ masking_rules[]  │  │      ↓             │
  │  here, no LLM   │  │ review_queue[]   │  │ RRF fusion (k=60)  │
  │       ↓         │  │ confidence_      │  │      ↓             │
  │ L2 qwen2.5:7b   │  │   summary        │  │ pii_category       │
  │  only when L1   │  │                  │  │  filter (post-     │
  │  is unsure      │  │ doc refs point   │  │  fusion)           │
  │       ↓         │  │ into rag/corpus/ │  │                    │
  │ confidence      │  └──────────────────┘  │ ← rag/ingest.py    │
  │  blending       │                        │   12 docs → 49     │
  └────┬───────┬────┘                        │   chunks (H2/H3)   │
       │       │                             └────────────────────┘
       │       └──────────────┐
       ▼                      ▼
┌──────────────┐      ┌──────────────┐
│ audit_log.db │      │ llm_cache.db │
│              │      │              │
│ every        │      │ exact-match  │
│ decision,    │      │ cache on the │
│ append-only  │      │ L2 call      │
└──────────────┘      └──────────────┘
```

### Data flow

```
column descriptor JSON
        │
        ▼
  rule layer (free, deterministic)
    name keyword match?  sample regex match?  checksum?
    both match      → 0.97, decided here, no LLM call
    safe-list name  → not PII 0.95, no LLM call
    otherwise       → escalate
        │
        ▼
  LLM layer (qwen2.5:7b, temperature=0, cached)
        │
        ▼
  confidence blending — agree → weighted; no corroboration → capped
    0.85; rule/LLM conflict → capped 0.70 so it always reaches review
        │
        ▼
  is_pii decided first, THEN a threshold per branch:
    PII     ≥ 0.80 → auto-configure, else → review queue
    not PII ≥ 0.60 → accepted,       else → review queue anyway
        │
        ▼
  masking config JSON  (masking_rules / review_queue / summary)
  + one audit_log.db row per decision
```

---

## Setup

Requires Python 3.10+ and [Ollama](https://ollama.com) running locally.

```bash
ollama pull qwen2.5:7b && ollama pull nomic-embed-text
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python rag/ingest.py
```

`rag/ingest.py` builds the retrieval index (`rag/index/`) and must run once
before the agent or the quality tests — retrieval reads the persisted index.
Expect `Ingested 49 chunks from 12 documents`.

Configuration is optional — every setting has a working default:

```bash
cp .env.example .env
```

### Run the tests

```bash
.venv/bin/pytest
```

26 tests, from the repository root. Needs Ollama running. First run takes a
few minutes; subsequent runs are much faster because the LLM cache is warm.

### Talk to the agent

```bash
.venv/bin/python agent/agent.py
```

Try: `What does DATE_SHIFT do?` · `Is column ref_code in table ORDERS PII?` ·
`What is the weather in Hyderabad?` · or paste a schema JSON array and then
ask `Generate a masking configuration for these results`.

### Regenerate the A/B model baseline

```bash
ollama pull qwen2.5:14b            # only needed for this
cd agent && ../.venv/bin/python tests/ab_comparison.py
```

---

## Design Decisions

**1. Hybrid detection — rules first, LLM only when the rules are unsure**

A deterministic layer (keyword dictionary + value regex + Luhn checksum)
resolves about 70% of the golden set with no LLM call. `qwen2.5:7b` is
invoked only for the remainder. Cost scales with schema *ambiguity*, not
schema size, which is what makes the 5,000-column target in SCALABILITY.md
tractable. It also means the auditable layer decides the easy cases, and the
probabilistic one only ever argues about genuinely hard ones.

**2. Two thresholds, not one confidence scale**

`is_pii` is settled first, from the rule and LLM signals; confidence is then
checked against a *different* threshold depending on which way it went — 0.80
for PII (below it, review), 0.60 for not-PII (below it, review anyway). The
second branch is deliberately beyond the task's literal contract: an
ungrounded low-confidence "not PII", with no rule-layer opinion to
cross-check it, is exactly the shape of a compliance miss, so it is never
silently cleared. QUALITY_CRITERIA.md originally specified a single scale;
implementing the blending logic showed that model was wrong, and it was
revised with a dated note rather than quietly left inconsistent.

**3. Raw tool-calling, and the model's arguments are thrown away**

No LangChain or LangGraph. All seven interactions are at most one tool call,
so a graph framework would add a dependency and an abstraction layer for a
problem simpler than the tool solving it, and would make the grounding test
(intercepting a tool call) harder rather than easier.

The agent uses Ollama's native tool-calling for tool *selection* only.
Testing showed `qwen2.5` picks the right tool reliably but fabricates
plausible arguments when the real data isn't in front of it — asked about one
named column, it invented an entire five-column schema. So every structured
argument is parsed from the message deterministically and the model's own
arguments are discarded. Grounding is likewise structural: documentation
questions reach `search_masking_docs` on a code path, and the citation is
appended by code from the retrieved chunk, not trusted to the model.

**4. Everything is logged; nothing learns automatically**

Every decision lands in `audit_log.db` — that is what makes "why was this
column masked?" answerable months later. The rule dictionary can grow from
LLM-suggested keywords, but only through an explicit human approval step,
never automatically. Auto-promoting an unreviewed suggestion into the
deterministic layer would destroy the exact property that layer exists for.
This is human review as a safety net, not a learning loop — no reward signal,
no training, no weights.

**5. Local models, tiered, with an exact-match cache**

`qwen2.5:7b` for both classification and the agent, `nomic-embed-text` for
embeddings. The Layer 2 call runs at `temperature=0` and is therefore meant to
be deterministic per input, which makes an exact-match cache (`llm_cache.db`)
safe: a hit returns precisely what a fresh call would have. Blending and audit
logging still run on every detection, cached or not, so the audit trail stays
complete. Repeated schema scans — the actual production pattern — mostly stop
calling the model at all.

---

## What I would do differently with more time

1. **Make `suggested_rule_keyword` actually fire.** The rule-promotion
   pipeline is built and tested, but the model has never once populated the
   field that feeds it across 100+ real decisions. See BLOCKERS.md — the
   plumbing works; the signal doesn't arrive.

2. **Fix short-keyword substring matching.** Three of the five known false
   positives come from `"pan"` matching inside `com·pan·y` and `"ip"` inside
   `descr·ip·tion`. Word-boundary matching for short keywords, while keeping
   compound matches like `date_of_birth`, is a real change to the matching
   rule and needs full re-verification — not something to rush.

3. **A ranked candidate list instead of one alternative.** With only two
   opinions (rule layer, LLM), `alternatives` in the review queue can hold at
   most one entry. Returning every category with any rule-layer signal would
   be cheap and strictly more informative.

4. **Widen the RAG eval set.** Ten queries over twelve documents, where I
   wrote both the corpus and the queries, is a weak independence guarantee.
   Recall@3 of 1.00 should be read as "hybrid retrieval works", not "retrieval
   is solved".

5. **Parallelise detection.** `detect_all` is sequential; escalated columns
   are I/O-bound on the model. A thread pool over just the escalated fraction
   is the obvious next step for the 5,000-column target.

---

## Test coverage

26 tests. `.venv/bin/pytest` from the repository root runs all of them.

| Area | Tests | What is actually asserted |
|---|---|---|
| `pii-detector/tests/` | 8 | Golden-set recall ≥ 0.90 and precision ≥ 0.70 (measured 1.00 / 0.75); the four contract tests from the task doc; promoted-keyword overlay works and an empty overlay is a no-op; a repeated identical column never reaches the model |
| `masking-generator/tests/` | 6 | Low confidence goes to `review_queue` and not `masking_rules`; every `documentation_reference` resolves to a real corpus file; summary counts reconcile; conflict alternatives; a real detector→generator integration run |
| `agent/tests/quality_tests.py` | 12 | All six required quality types — semantic correctness, grounding via tool-call interception, out-of-scope rejection, PII recall/precision regression, masking-config completeness, plus the A/B baseline as a script |

Evaluation reports (measured, not asserted): `pii-detector/tests/eval_report.md`,
`rag/eval/recall_report.md`, `agent/tests/ab_baseline_results.md`.

**What is not tested, and why**

- **Real customer schema accuracy.** The golden set is data I invented. Only a
  customer-labelled sample can support an accuracy claim for a given customer —
  QUALITY_CRITERIA.md describes that validation step.
- **Concurrency and load.** Nothing here runs in parallel yet, so there is
  nothing to test; see improvement 5 above.
- **Prose quality of agent answers.** Tests assert grounding, citation, and
  concept coverage — properties that survive rewording. Whether an answer
  *reads* well is not asserted, because the mechanical proxies for it punish
  harmless rephrasing and still miss confident wrongness.
- **The rule-promotion loop end to end.** Verified with synthetic data only;
  see BLOCKERS.md.

Known limitations are documented in **BLOCKERS.md** rather than left for the
reader to discover.
