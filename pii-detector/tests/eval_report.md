# PII Detector — Evaluation Report

Generated: 2026-08-03, from a live run of `detector.py` against `schema_test_cases.json` (30 cases). `test_recall_on_golden_set` and `test_precision_on_golden_set` in `test_detector.py` assert these same thresholds on every test run, so those two numbers stay honest even without a report-generation script. The others in the table below are hand-measured and are only as current as the date above — an earlier revision of this report claimed an auto-configuration rate of 1.00 that had already drifted to 0.93, which is exactly the failure mode a hand-maintained report invites.

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
| Precision | ≥ 0.70 | 0.79 | PASS |
| Auto-config rate (among true positives) | ≥ 0.80 | 0.93 | PASS |
| Category accuracy (among true positives) | — | 1.00 | — |

Confusion counts: TP=15 FP=4 FN=0 TN=11

The one true positive not auto-configured is `CUSTOMERS.home_address`: the
rule layer matched ADDRESS, the LLM disagreed, and blend case 3c caps a
rule/LLM conflict at 0.70 precisely so disagreement can never auto-configure.
It stays `is_pii=true` — recall is unaffected — and lands in the review queue,
which is the intended behaviour rather than a miss.

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

**Short keywords matching inside longer words.** `name_matches` tested every
keyword as a substring of the underscore-joined column name — necessary for
compound terms like `date_of_birth`, but it also fired `"pan"` (Primary
Account Number) inside `com-PAN-y` and `"ip"` inside `descr-IP-tion` and
`sh-IP_date`, producing three of the five false positives. Single-word
keywords now require a whole-token match; multi-word keywords keep substring
matching. Measured before changing anything: the new rule flips exactly those
three columns and nothing else in the golden set. Precision 0.75 -> 0.79,
false positives 5 -> 4, Layer 1 resolution 70% -> 73%.

The trade-off is agglutinative names where the term is fused into a longer
word (German `nachname`, Indonesian `nomor_telepon`). Those now fall through
to the LLM on sample evidence and surface as rule-promotion candidates —
which is the designed path for a real dictionary gap, rather than relying on
a coincidental character match.

## Errors

**False negatives:** none in this run.

**False positives (routed to review queue, not silently wrong):**

- `ORDERS.order_date` — flagged PHONE (0.55). The PHONE value regex accepts a date-shaped digit/hyphen string.
- `PRODUCTS.company_name` — flagged FULL_NAME (0.55). `"Acme Corp"` satisfies the FULL_NAME value regex; a company name is shaped exactly like a person's name.
- `PRODUCTS.sku` — flagged ACCOUNT_NUMBER (0.55). `"SKU-1234"` matches the `[A-Za-z]{2,4}-\d{4,10}` account-prefix pattern.
- `SHIPMENTS.ship_date` — flagged PHONE (0.55). Same date-shaped-string cause as `order_date`.

All four now score exactly 0.55 — a **sample-only** rule match, with no name
signal at all. That is a single remaining root cause: value regexes that are
loose enough to match non-PII strings. In every case the LLM disagreed, blend
case 3c capped the result below the auto-configure threshold, and the column
reached the review queue rather than being masked.

## Layer 1 vs Layer 2 Split

- Resolved at Layer 1 (rule engine only, no LLM call): 22/30 (73%)
- Escalated to Layer 2 (LLM): 8/30, of which only 2 (`next_of_kin`,
  `ref_code`) had zero rule-layer opinion at all -- the rest were
  cross-checked against a partial rule signal, not LLM-alone.
