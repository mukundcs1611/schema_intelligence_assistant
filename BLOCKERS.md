# Blockers

Open issues only. Things found and fixed during development are recorded
where they belong -- detector fixes in `pii-detector/tests/eval_report.md`,
architectural lessons in `README.md`'s design decisions -- rather than kept
here as resolved entries.

## PII detector: 5 known false positives, root cause now diagnosed but not fixed

`eval_report.md` has documented these 5 false positives (all correctly
routed to the review queue, never silently wrong) since Day 1B, but never
diagnosed *why* each one fires. Verified directly just now:

- `ORDERS.order_date` -> `PHONE` and `PRODUCTS.sku` -> `ACCOUNT_NUMBER`:
  genuine value-regex looseness. `PHONE`'s pattern matches date-shaped
  digit/hyphen strings like `"2026-05-01"`; `ACCOUNT_NUMBER`'s
  `[A-Za-z]{2,4}-\d{4,10}` prefix pattern matches SKU-shaped strings like
  `"SKU-1234"` just as easily as real account numbers.
- `PRODUCTS.company_name` -> `CREDIT_CARD`, `PRODUCTS.description` ->
  `IP_ADDRESS`, `SHIPMENTS.ship_date` -> `IP_ADDRESS`: **not a regex
  problem at all** -- the same substring-matching mechanism behind the
  `nachname`/`"name"` surprise found earlier in this session.
  `name_matches()` checks whether a known keyword is a *substring* of the
  column name (needed to catch compound keywords like `date_of_birth`),
  and short keyword fragments coincidentally land inside unrelated English
  words: `"pan"` (a real credit-card term, Primary Account Number) is
  embedded in `com-PAN-y`; `"ip"` is embedded in both `descr-IP-tion` and
  `sh-IP_date`. Confirmed directly: `name_matches("company_name",
  "CREDIT_CARD")`, `name_matches("description", "IP_ADDRESS")`, and
  `name_matches("ship_date", "IP_ADDRESS")` all return `True`.

Not fixed. A real fix likely means requiring short keywords (`"pan"`,
`"ip"`, anything under ~4 characters) to match on word boundaries rather
than raw substrings, while still allowing legitimate compound-keyword
substring matches like `date_of_birth`. That's a real design change to
`name_matches()`'s matching rule, not a one-line patch, and risks
regressing the compound-keyword cases it was built to catch -- needs the
same fresh-process, full-suite re-verification treatment as the earlier
hash-seed fix before it'd be safe to ship.

## Agent: out-of-scope vs. missing-data boundary misfires on contrived queries

**Status:** Known and bounded. Not fixed.

When the tool-selection call returns no tool at all, that outcome is
ambiguous between two genuinely different situations: a question that is
out of scope entirely, and an in-scope request that simply has no data
attached (the task doc's interaction 7, `"Mask this column: [no schema
provided]"`). The agent disambiguates with a narrow secondary check --
the message must contain both an action verb (`mask`, `analyse`, `detect`,
`check`, ...) and a data noun (`column`, `schema`, `table`, `field`).

Adversarial testing found this misfires on queries that borrow data
vocabulary for a non-data purpose:

| Query | Response | Correct? |
|---|---|---|
| "What is the capital of France?" | out-of-scope refusal | yes |
| "How do I mask my face in a photo?" | out-of-scope refusal | yes (verb matched, no data noun) |
| "What parameters does EMAIL_MASK accept?" | grounded doc answer | yes |
| "Can you check the weather columns for Hyderabad?" | "I don't have a schema to analyze yet" | **no** -- should refuse |

The failure is bounded in the direction that matters: a misfire asks for
data the agent doesn't have, and never fabricates a detection result or
answers the out-of-scope question. It also only triggers on queries that
pair a data verb with a data noun in a non-data context, which is a
contrived shape rather than a natural user question.

A real fix likely means replacing the keyword pair with a second narrow
LLM classification call (in-scope-but-dataless vs. out-of-scope) rather
than extending the keyword lists, which would repeat the substring
brittleness already documented above under the false-positives section.
Not attempted -- the cost is an extra LLM call on every no-tool-selected
message, for a failure mode that is bounded and rare.

## RAG retrieval: known ranking weaknesses, not tuned away

From `rag/eval/recall_report.md`, already documented there, repeated here
for visibility:

- **q4 chunk-ranking**: for `"what parameters does EMAIL_MASK accept"`,
  `email_mask.md`'s own `#parameters` chunk only reaches rank 3, behind
  two `masking_functions_overview.md` chunks that mention "EMAIL_MASK" by
  name and out-rank it on BM25 signal. Recall@3 still passes at the
  document level, but the single best chunk isn't top-ranked. Deliberately
  not tuned against the 10-query eval set, to avoid fitting the metric
  rather than improving retrieval generally.
- **Coverage gap**: `data_masking_overview.md` and
  `masking_functions_overview.md` are not the expected answer for any of
  the 10 eval queries -- their retrieval quality is unverified by this eval
  set (see recall_report.md's coverage-gap section for why they were
  deprioritized).

## PII detector: structural gap on zero-rule-signal columns, only partially mitigated

From `eval_report.md`'s "Fixed During Evaluation" section: the
`SYSTEM_PROMPT` fix for the `next_of_kin` false negative (sample values as
primary evidence over column-name surface meaning) fixed that specific
failure mode, not the underlying class. Any column with zero rule-layer
signal at all still depends entirely on the LLM getting it right
unprompted, with no second, independent check in that path. This is
disclosed as an architectural limitation, not something believed fixable
within this system's two-signal (rule + LLM) design -- it's the kind of
thing that belongs in `CUSTOMER_VALUE.md`'s risk/limitations section as an
honest disclosure, not something to silently claim as solved.

## Parked, not a bug: ranked/multi-candidate alternatives

Discussed and deliberately deferred, not attempted: `DetectionResult`'s
`alternative_category` can only ever hold one value (the rule layer's
rejected guess in a conflict), because the system only ever has two
opinions total (rule layer, LLM). A genuinely ranked list of alternatives
would need either the rule layer to return all categories with any signal
(cheap, low-risk) or the LLM to return multiple ranked candidates (risky --
invites the same fabrication problem this session kept finding elsewhere).
Rule-layer-side ranking was judged legitimate but out of scope given time
remaining; not started.
