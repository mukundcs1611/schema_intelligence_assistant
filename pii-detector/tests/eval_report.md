# PII Detector — Evaluation Report

Generated: 2026-08-01, from a live run of `detector.py` against `schema_test_cases.json` (30 cases). `test_recall_on_golden_set` and `test_precision_on_golden_set` in `test_detector.py` assert these same thresholds on every test run, so these numbers stay honest even without a report-generation script.

## Golden Set

- Total columns: 30 (15 PII / 15 non-PII by label)
- Categories covered: 10 of 10 PII categories

## Measured Metrics vs. QUALITY_CRITERIA.md Targets

| Metric | Target | Measured | Result |
|---|---|---|---|
| Recall | ≥ 0.90 | 0.93 | PASS |
| Precision | ≥ 0.70 | 0.74 | PASS |
| Auto-config rate (among true positives) | ≥ 0.80 | 0.93 | PASS |
| Category accuracy (among true positives) | — | 1.00 | — |

Confusion counts: TP=14 FP=5 FN=1 TN=10

## Errors

**False negatives (missed PII — the costly failure mode):**

- `EMPLOYEES.next_of_kin` — expected FULL_NAME, detector said not-PII. Reasoning: The term 'next_of_kin' typically refers to a family member and not an individual's full name.

**False positives (routed to review queue, not silently wrong):**

- `ORDERS.order_date` — flagged PHONE (confidence 0.55), expected non-PII. Reasoning: Rule layer matched PHONE but LLM disagreed; routed to review pending human judgement. The column name and data content do not indicate personal information.
- `PRODUCTS.company_name` — flagged CREDIT_CARD (confidence 0.6), expected non-PII. Reasoning: Rule layer matched CREDIT_CARD but LLM disagreed; routed to review pending human judgement. Company names are not PII.
- `PRODUCTS.sku` — flagged ACCOUNT_NUMBER (confidence 0.55), expected non-PII. Reasoning: Rule layer matched ACCOUNT_NUMBER but LLM disagreed; routed to review pending human judgement. SKU is an identifier for products, not individuals.
- `PRODUCTS.description` — flagged IP_ADDRESS (confidence 0.6), expected non-PII. Reasoning: Rule layer matched IP_ADDRESS but LLM disagreed; routed to review pending human judgement. Column name 'description' does not indicate any PII.
- `SHIPMENTS.ship_date` — flagged IP_ADDRESS (confidence 0.6), expected non-PII. Reasoning: Rule layer matched IP_ADDRESS but LLM disagreed; routed to review pending human judgement. The column name 'ship_date' indicates a date related to shipment, not a person's birth date.

## Layer 1 vs Layer 2 Split

- Resolved at Layer 1 (rule engine only, no LLM call): 19/30 (63%)
- Escalated to Layer 2 (LLM): 11/30
