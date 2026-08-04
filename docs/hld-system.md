# HLD — Schema Intelligence Assistant

Whole-system view. One conversational entry point, three tools, two storage
layers, two offline jobs. Everything runs on local Ollama.

```mermaid
flowchart TB
    USER(["User<br/>agent REPL or library"])

    subgraph AGENT["agent/agent.py"]
        direction TB
        PARSE["1 · Deterministic parse<br/>schema JSON? · column X in table Y?<br/>generate masking config?"]
        SELECT["2 · Ollama tool-calling<br/>qwen2.5:7b · temperature=0<br/>selection only — arguments discarded"]
        NOTOOL["3 · No tool selected<br/>refuse, or ask for missing data"]
        PARSE -->|"no structural match"| SELECT
        SELECT -->|"tool_calls empty"| NOTOOL
    end

    subgraph TOOLS["agent/tools.py — thin wrappers, no logic of their own"]
        T1["detect_pii_columns"]
        T2["generate_masking_config"]
        T3["search_masking_docs"]
    end

    subgraph DETECT["pii-detector/"]
        L1["Layer 1 · pii_patterns.py<br/>keywords + value regex + Luhn<br/>73% resolve here, no LLM"]
        L2["Layer 2 · detector.py<br/>qwen2.5:7b · temperature=0<br/>only when Layer 1 is unsure"]
        BLEND["Confidence blend<br/>agree → weighted · uncorroborated → cap 0.85<br/>conflict → cap 0.70, always reviewed"]
        L1 -->|"score < 0.90"| L2 --> BLEND
    end

    GEN["masking-generator/generator.py<br/>DetectionResult[] → masking_rules[]<br/>+ review_queue[] + summary<br/>pure transform, no LLM"]

    subgraph RAGSYS["rag/"]
        RET["retrieve.py<br/>vector + BM25 → RRF k=60<br/>category filter after fusion"]
        IDX[("rag/index/<br/>49 chunks from 12 docs")]
        IDX --> RET
    end

    subgraph STORE["Storage — SQLite, no external services"]
        AUDIT[("audit_log.db<br/>every decision, append-only")]
        CACHE[("llm_cache.db<br/>exact-match, prompt-versioned")]
    end

    subgraph OFFLINE["Offline jobs"]
        ING["rag/ingest.py<br/>corpus → chunks → embeddings + BM25"]
        PROMO["pii-detector/promote_rules.py<br/>reviewer approves suggested keywords"]
    end

    USER --> PARSE
    PARSE -->|"schema / single column"| T1
    PARSE -->|"config request"| T2
    SELECT -->|"documentation question"| T3
    SELECT -->|"PII-shaped, no data"| T1
    NOTOOL --> USER

    T1 --> L1
    T2 --> GEN
    T3 --> RET

    BLEND --> RESULT["DetectionResult[]"]
    RESULT --> GEN
    RESULT -.->|"held in agent session state<br/>for a later config request"| T2

    L2 <-->|"read / write"| CACHE
    BLEND -->|"one row per decision"| AUDIT
    GEN --> OUT["Masking config JSON"]
    RET --> ANSWER["Grounded answer<br/>+ citation appended by code"]
    OUT --> USER
    ANSWER --> USER

    CORPUS["rag/corpus/*.md"] --> ING --> IDX
    AUDIT -->|"suggested_rule_keyword"| PROMO
    PROMO -->|"approved only"| YAML[("promoted_rules.yaml")]
    YAML -.->|"mtime-checked, next call<br/>no restart"| L1

    GEN -.->|"static anchor map,<br/>not a live query"| IDX
```

## Why it is shaped this way

| Decision | Reason |
|---|---|
| Deterministic parse **before** any LLM call | Most requests are structurally decidable. A model adds latency and failure modes, not accuracy. |
| Model picks the tool, code builds the arguments | `qwen2.5` selects reliably but fabricates arguments — asked about one column it invented a five-column schema. |
| Rule layer first, LLM only when unsure | Cost tracks schema *ambiguity*, not schema *size*. |
| Conflict capped at 0.70, below the 0.80 auto bar | Rule/LLM disagreement can never auto-configure. |
| Promotion needs a human | An unreviewed suggestion entering the deterministic layer destroys the property that layer exists for. |
| Everything to SQLite | "Why was this column masked?" must be answerable months later. |

## Model and cost profile

| Component | Model | When it runs |
|---|---|---|
| Rule engine | none | every column |
| Detector Layer 2 | `qwen2.5:7b` | only unresolved columns, cached |
| Agent tool selection | `qwen2.5:7b` | only structurally ambiguous messages |
| Agent answer generation | `qwen2.5:7b` | documentation questions only |
| Embeddings | `nomic-embed-text` | ingest, and once per RAG query |

`qwen2.5:14b` was the original agent choice and was reversed on measured
evidence — see `agent/tests/ab_baseline_results.md`.
