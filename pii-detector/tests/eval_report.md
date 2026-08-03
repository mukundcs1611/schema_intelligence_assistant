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

## Also fixed during evaluation

**`suggested_rule_keyword` never populated.** The classifier is instructed to
propose a keyword whenever it identifies PII the rule dictionary missed --
the signal that feeds the human-reviewed rule-promotion loop. Across 100+
escalated decisions it returned `null` every time, including on verified
zero-signal columns it classified correctly. Root cause was prompt structure,
not model capability: the instruction sat *after* the JSON schema block, and
its phrasing ("if ... return it") made `null` the comfortable default. Moving
it into the numbered rules block and inverting the default ("you MUST fill
this in ... return null ONLY when ...") fixed it on the first attempt, with
correct discrimination -- `elektropost` -> `"elektropost"`, `shimei` ->
`"shimei"`, but `ref_code` -> `null`, since that name is contentless as a
standing rule. Classification metrics above are unchanged by the edit.

**Redundant keyword suggestions.** `_blend` gated `suggested_rule_keyword`
only on whether the LLM said PII, never on whether the keyword dictionary had
already matched the column *by name*. A column the dictionary already catches
would still produce a suggestion to add a keyword for it -- a no-op a reviewer
still has to read. `_score_rule_layer` now returns `name_matched` explicitly
(rather than leaving it to be inferred from whether the score is 0.60 or 0.55,
which would break silently if those scores were retuned) and `_blend` gates on
it. Verified both directions on live columns: `handy_nr` (no dictionary
signal) still yields `"handy_nr"`; `nomor_telepon` (already caught by the
`"tel"` keyword) is correctly suppressed.

**Prompt changes were invisible to the cache.** `make_cache_key` keyed on
model and column inputs but not on the prompt, so any `SYSTEM_PROMPT` edit
would have been silently ignored for every already-cached column. A hash of
the prompt is now part of the key. This did not affect the fix above -- the
test column happened not to be cached -- but it would have made the next
prompt change appear to do nothing.

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
