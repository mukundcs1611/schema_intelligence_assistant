Implementation: Python

# Schema Intelligence Assistant

An AI-powered tool that analyses database schemas, identifies PII columns,
suggests masking rules, and answers natural language questions about data
masking — reducing PS team onboarding time from 3–4 days to under 4 hours.

---

## Architecture

```
                        ┌─────────────────────────────┐
                        │     User / PS Team           │
                        │  (terminal / agent chat)     │
                        └──────────────┬──────────────┘
                                       │
                                       ▼
                        ┌─────────────────────────────┐
                        │      agent.py               │
                        │  LangGraph StateGraph        │
                        │  qwen2.5:14b (local Ollama)  │
                        │                             │
                        │  Tools:                     │
                        │  ├── detect_pii_columns      │
                        │  ├── generate_masking_config │
                        │  └── search_masking_docs     │
                        └──────────────┬──────────────┘
                                       │
                                       ▼
                        ┌─────────────────────────────┐
                        │      pipeline.py             │
                        │  SchemaIntelligencePipeline  │
                        │  (stable spine — contracts   │
                        │   fixed, modules replaceable)│
                        └──┬──────────┬───────────┬───┘
                           │          │           │
               ┌───────────▼─┐  ┌─────▼──────┐  ┌▼────────────────┐
               │ detector.py  │  │generator.py│  │  retrieve.py    │
               │              │  │            │  │                 │
               │ Layer 1:     │  │Takes       │  │ Hybrid:         │
               │ Rule engine  │  │DetectionR- │  │ Vector search   │
               │ (pii_        │  │esult list  │  │ (nomic-embed)   │
               │  patterns.py)│  │            │  │ + BM25          │
               │              │  │Produces    │  │ fused via RRF   │
               │ Layer 2:     │  │MaskingConf-│  │                 │
               │ qwen2.5:7b   │  │ig JSON     │  │ 12 corpus docs  │
               │ (uncertain   │  │            │  │ pii_category    │
               │  cases only) │  │auto_rules  │  │ metadata filter │
               │              │  │review_queue│  │                 │
               └──────┬───────┘  └─────┬──────┘  └────────────────┘
                      │                │
                      └────────┬───────┘
                               │
                               ▼
                  ┌────────────────────────┐
                  │    audit_logger.py     │
                  │    SQLite backend      │
                  │    audit_log.db        │
                  │                        │
                  │ Every decision logged: │
                  │ automated + human      │
                  └────────────────────────┘
                               │
                               ▼
                  ┌────────────────────────┐
                  │   Feedback Loop        │
                  │   python demo.py       │
                  │      --improve         │
                  │                        │
                  │ Corrections → patterns │
                  │ Patterns → new rules   │
                  │ Rules → recall improves│
                  └────────────────────────┘
```

### Data Flow

```
Schema JSON in
      │
      ▼
PiiDetector
  Layer 1: rules (name dict + sample regex + datatype signal)
  conf = 3/3 signals → 0.95 → AUTO  |  ambiguous → Layer 2
  Layer 2: qwen2.5:7b → structured JSON → confidence blend
  conf ≥ 0.80 → auto-configure  |  conf < 0.80 → review queue
      │
      ▼
MaskingConfigGenerator
  high confidence detections → masking_rules[]
  low confidence detections  → review_queue[]
  documentation reference    → looked up from RAG corpus
      │
      ▼
MaskingConfig JSON out
  + audit_log.db entry for every decision
```

---

## Setup

### Prerequisites

```bash
# Python 3.10+
python3 --version

# Ollama
ollama --version

# Pull models (do this first — 14b takes a few minutes)
ollama pull qwen2.5:7b
ollama pull qwen2.5:14b
ollama pull nomic-embed-text
```

### Install

```bash
git clone https://github.com/mukundcs1611/schema_intelligence_assistant
cd schema_intelligence_assistant
cp .env.example .env
pip install -r requirements.txt
```

### Ingest RAG corpus

```bash
python rag/ingest.py
```

### Run tests

```bash
pytest pii-detector/tests/
pytest masking-generator/tests/
pytest agent/tests/quality_tests.py
```

### Run demo (end to end)

```bash
# Detect PII in a sample schema
python demo.py --schema pii-detector/tests/demo_schema.json

# Review queue — interactive HITL
python demo.py --review

# Improve rules from audit log
python demo.py --improve

# Re-run to see improvement
python demo.py --schema pii-detector/tests/demo_schema.json
```

### Run agent (conversational)

```bash
python agent/agent.py
```

---

## Design Decisions

**1. Hybrid detection: rules first, LLM only for uncertain cases**

A rule engine (name dictionary + sample regex + datatype signal) handles
~80% of columns at zero LLM cost. qwen2.5:7b is called only for columns
where rule signals are ambiguous. This keeps LLM cost proportional to
schema complexity, not schema size. A 5,000-column schema with standard
naming conventions costs almost nothing to classify.

**2. No two-agent verifier pattern**

A generator + critic (LLM-as-judge) pattern was considered and rejected.
The review queue provides the same protection at zero additional API cost.
LLM errors are correlated — a second call to the same model family has
the same blind spots as the first. A human reviewer is the uncorrelated
safety net.

**3. pipeline.py as the stable spine**

All modules communicate through fixed JSON contracts. The detector,
generator, retriever, and audit logger are replaceable without changing
anything downstream. The agent calls pipeline methods, not modules
directly. This design supports n+1 iterations: new PII categories,
swapped models, and per-customer threshold tuning all happen without
architectural changes.

**4. SQLite for audit logging**

Zero infrastructure, queryable, survives upgrades, readable by humans.
Every automated and human decision is persisted. The feedback loop reads
the audit log to find correction patterns and propose new rules. At
production scale (500+ customers) this migrates to a centralised
time-series store — the schema is identical, only the backend changes.

**5. Confidence threshold in .env — not hardcoded**

Default 0.80. Tunable per customer deployment without code changes.
During PS team pilot, the threshold is validated against a customer-labelled
sample before the tool runs on the full schema. If the threshold must drop
below 0.60 to maintain ≥80% auto-configuration rate, the tool is flagged
as poorly calibrated for that schema type.

**6. Local Ollama only — no external API dependencies**

No API keys. No rate limits. No cost per call during development.
qwen2.5:7b for classification (4.7GB, fast on M2 Pro via Metal).
qwen2.5:14b for the conversational agent (9GB, reliable tool-calling).
nomic-embed-text for embeddings (274MB, runs on CPU).
The cost story for SCALABILITY.md is honest: near-zero marginal cost
per column on self-hosted infrastructure.

---

## What I Would Do Differently With More Time

1. **Customer-specific fine-tuning** — collect PS team corrections per
   industry vertical and fine-tune a small classifier. Current approach
   relies on qwen2.5:7b zero-shot generalisation for ambiguous cases.

2. **Embedding-based pattern matching for Layer 1** — replace the static
   name dictionary with semantic similarity against a PII pattern library.
   Handles synonyms and non-English names without manual dictionary updates.

3. **Streaming agent responses** — current agent returns complete responses.
   For large schemas (500+ columns), streaming detection results as they
   arrive would significantly improve perceived performance.

4. **Per-customer threshold calibration UI** — the PS team currently tunes
   the threshold via .env. A simple web interface showing recall vs
   auto-configuration rate trade-off curves would make this decision
   visible and auditable.

5. **RAG corpus versioning** — when a new masking function is released,
   the corpus is re-ingested manually. An automated pipeline watching
   a docs repository and triggering re-ingestion on change would keep
   the RAG current without PS team intervention.

---

## Test Coverage Summary

| What is tested | How |
|---|---|
| PII detection accuracy | Golden set recall/precision on 30 labelled columns |
| Confidence threshold routing | Every conf < 0.80 PII detection in review queue |
| Individual PII categories | Unit tests for EMAIL, SSN, PHONE, CREDIT_CARD, ACCOUNT_NUMBER, NATIONAL_ID, DATE_OF_BIRTH, IP_ADDRESS, FULL_NAME, ADDRESS |
| Non-PII not flagged | transaction_id, quantity, ship_date, company_name |
| RAG retrieval quality | Recall@3 on 10 eval queries |
| Masking config completeness | All high-confidence PII columns in masking_rules[] |
| Review queue population | All low-confidence PII columns in review_queue[] |
| Agent grounding | Tool call interception — search_masking_docs called before doc answers |
| Agent out-of-scope rejection | Capital of France, weather questions refused |
| Agent missing input handling | No schema provided — agent asks, does not hallucinate |
| Recall regression | Golden set re-run on every agent test run |
| A/B model baseline | 5 standard queries scored against rubric |

**What is not tested:**
- Real customer schema accuracy (requires customer-labelled sample — by design)
- LLM response latency under load
- Concurrent schema analysis requests
- RAG corpus staleness detection
