# Blockers

## Rule-promotion keyword suggestions not firing from the LLM

**Status:** Deferred. Does not block any JD-required deliverable -- see
"Why this isn't blocking submission" below.

**Scope note:** this affects an optional, self-initiated capability (see
below), not the core PII detection engine (Part 1B) or the RAG/masking-
generator work (Part 2). Detection accuracy, recall, precision, and
review-queue population -- everything graded under "PII detection accuracy
+ testing" -- are entirely unaffected by this.

### What's blocked

`pii-detector/detector.py`'s `SYSTEM_PROMPT` instructs the LLM
(`qwen2.5:7b`) to return a `suggested_rule_keyword` whenever it classifies
a column as PII using a term the rule-layer keyword dictionary should have
caught but didn't. This was meant to feed a human-reviewed promotion
pipeline (`pii-detector/promote_rules.py`, `promoted_rules.yaml`) that lets
the rule dictionary grow from real, LLM-observed vocabulary gaps without a
code change or redeploy -- a claim `QUALITY_CRITERIA.md` Section 5 makes.

In practice, across every real LLM-escalated decision observed during this
project (100+, across multiple full golden-set runs) and every deliberately
constructed test case -- including a verified true zero-signal case
(`elektropost`, an obfuscated German synonym for "email address", zero
rule-layer name or sample match, correctly classified `EMAIL` at 0.85
confidence) -- the model has never once populated this field.

### What was verified

- The instruction itself is reachable and well-formed in the prompt sent
  to the model.
- The failure isn't a downstream bug: the promotion plumbing that reads
  this field (`get_promoted_keywords()`'s mtime-cached YAML overlay in
  `pii_patterns.py`, `promote_rules.py`'s reviewer CLI) is built and
  independently verified against synthetic seed data -- approving a
  keyword is picked up by the very next `detect()` call, in a fresh
  process, with no restart.
- The gap is specifically the model not reliably attending to a secondary
  field in a multi-field JSON response, not a logic error in how the field
  is used once populated.

### A related, currently-unobservable bug found while investigating

`_blend()`'s `suggested_keyword` computation is gated only on
`llm_is_pii`, not on whether the rule layer's *name* dictionary already
matched. When `rule_category` is set via a sample-only match
(`rule_score == 0.55`, name didn't match), a suggestion is legitimate --
the name genuinely has a dictionary gap. When `rule_category` is set via a
name match (`rule_score == 0.60`), the name dictionary already caught the
term, and a suggestion would be redundant. `_blend` currently can't tell
these two cases apart. This has caused zero observed incorrect behavior so
far, purely because the LLM has never populated the field at all -- it's a
fix that matters once the primary blocker above is resolved, not before.

### Not attempted, given time constraints

Prompt rewording, reordering the instruction earlier in `SYSTEM_PROMPT`,
or trying `qwen2.5:14b` in place of `qwen2.5:7b` for this specific field --
all plausible next steps, none tried yet.

### Why this isn't blocking submission

`promote_rules.py` and `promoted_rules.yaml` are deliberately held out of
commits until this is resolved. Nothing in the JD's Day 1, Day 2, or Day 3
deliverable list depends on rule-promotion working -- it is an
architecture commitment made to ourselves in `QUALITY_CRITERIA.md`, not a
graded capability.

---

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

## Agent: tool-selection non-determinism (FIXED, recorded for the record)

Found while writing the quality test suite, not by inspection: the
grounding-enforcement test for the GDPR question passed when run manually
and failed under pytest, minutes apart, with no code change in between.
Root cause: `_select_tool()` called the model without `options={"temperature": 0}`,
so tool selection varied run to run -- the same question selected
`search_masking_docs` sometimes and no tool at all other times. That made
the grounding rule (the task doc's hard requirement that documentation
questions must always retrieve first) *intermittent* rather than
guaranteed.

Fixed by setting `temperature=0` on the tool-selection call, matching what
`detector.py` already did everywhere. Verified with 5 consecutive
selections on the previously-flaky query, all consistent. Recorded here
because the class of bug is worth remembering: a flaky grounding rule is
worse than a broken one, since it passes tests often enough to look
correct.

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
