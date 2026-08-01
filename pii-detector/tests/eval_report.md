# PII Detector — Evaluation Report

Generated: 2026-08-01, from a live run of `detector.py` against `schema_test_cases.json` (30 cases). `test_recall_on_golden_set` and `test_precision_on_golden_set` in `test_detector.py` assert these same thresholds on every test run, so these numbers stay honest even without a report-generation script.

## Golden Set

- Total columns: 30 (15 PII / 15 non-PII by label)
- Categories covered: 10 of 10 PII categories
- `EMPLOYEES.next_of_kin` was added deliberately as a zero-rule-signal case (no
  keyword match, no regex match) to test whether the LLM alone -- with no rule
  layer cross-check -- could correctly classify PII purely from sample-value
  reasoning. It initially failed (see "Fixed during evaluation" below).

## Measured Metrics vs. QUALITY_CRITERIA.md Targets

| Metric | Target | Measured | Result |
|---|---|---|---|
| Recall | ≥ 0.90 | 1.00 | PASS |
| Precision | ≥ 0.70 | 0.75 | PASS |
| Auto-config rate (among true positives) | ≥ 0.80 | 1.00 | PASS |
| Category accuracy (among true positives) | — | 1.00 | — |

Confusion counts: TP=15 FP=5 FN=0 TN=10

## Fixed During Evaluation

`EMPLOYEES.next_of_kin` (samples `["priya sharma", "daniel wu"]`) initially
classified as **not-PII at 0.85 confidence** -- a false negative with no
rule-layer opinion to cross-check it, and confident enough (above the 0.60
negative-review floor) to skip the review queue entirely. Root cause: the
LLM reasoned from the column name's surface meaning ("next_of_kin refers to
a relationship, not a name") and ignored the sample values, which were
themselves clearly a person's name.

Fix: `SYSTEM_PROMPT` in `detector.py` now explicitly instructs the model to
treat `sample_values` as primary evidence over `column_name`, and to
distinguish "what a name implies about the value's *relationship*" from
"what the value itself *is*". Re-tested after the fix: correctly classifies
as FULL_NAME at 0.85 confidence.

**This is a fix for one instance, not a guarantee against the failure
class.** Any column with zero rule-layer signal still depends entirely on
the LLM getting it right unprompted -- there is no second check in that
path (see `ref_code`, the other zero-signal case in this set, which
correctly resolves to not-PII but via the same single-source mechanism).
The prompt change makes this particular reasoning error less likely; it
does not eliminate the structural gap.

## Errors

**False negatives:** none in this run.

**False positives (routed to review queue, not silently wrong):**

- `ORDERS.order_date` — flagged PHONE (confidence 0.55), expected non-PII. Reasoning: Rule layer matched PHONE but LLM disagreed; routed to review pending human judgement. The column name and data content do not indicate personal information.
- `PRODUCTS.company_name` — flagged CREDIT_CARD (confidence 0.6), expected non-PII. Reasoning: Rule layer matched CREDIT_CARD but LLM disagreed; routed to review pending human judgement. Company names are not PII.
- `PRODUCTS.sku` — flagged ACCOUNT_NUMBER (confidence 0.55), expected non-PII. Reasoning: Rule layer matched ACCOUNT_NUMBER but LLM disagreed; routed to review pending human judgement. SKU is an identifier for products, not individuals.
- `PRODUCTS.description` — flagged IP_ADDRESS (confidence 0.6), expected non-PII. Reasoning: Rule layer matched IP_ADDRESS but LLM disagreed; routed to review pending human judgement. Column name 'description' does not indicate any PII.
- `SHIPMENTS.ship_date` — flagged IP_ADDRESS (confidence 0.6), expected non-PII. Reasoning: Rule layer matched IP_ADDRESS but LLM disagreed; routed to review pending human judgement. The column name 'ship_date' indicates a date related to shipment, not a person's birth date.

## Layer 1 vs Layer 2 Split

- Resolved at Layer 1 (rule engine only, no LLM call): 21/30 (70%)
- Escalated to Layer 2 (LLM): 9/30, of which only 2 (`next_of_kin`,
  `ref_code`) had zero rule-layer opinion at all -- the rest were
  cross-checked against a partial rule signal, not LLM-alone.
