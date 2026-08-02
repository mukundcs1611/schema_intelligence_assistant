# RAG Retrieval — Evaluation Report

Generated from a live run of `retrieve.py` against `masking_queries.json`
(10 queries) over the index built by `ingest.py` from `rag/corpus/` (12
documents, 49 chunks after H2/H3 splitting).

## Method

For each query: hybrid retrieval (cosine similarity + BM25, fused via
Reciprocal Rank Fusion, k=60), top_k=3, no `pii_category_filter` applied
(filter is an optional narrowing the agent can apply when it already knows
the category -- these queries test the ranker's unfiltered accuracy, which
is the harder and more meaningful bar). A query counts as a hit if the
expected document appears anywhere in the top 3 retrieved chunks' source
files, regardless of which specific chunk or rank position within the 3.

## Result

**Recall@3 = 10/10 = 1.00** (target ≥ 0.70, PASS)

| Query | Expected doc | Type | Hit rank | Top-3 retrieved docs |
|---|---|---|---|---|
| q1: "What does DATE_SHIFT do..." | date_shift.md | near_title | 1 | date_shift, date_shift, date_shift |
| q2: "How do I comply with GDPR..." | gdpr_ccpa_compliance.md | near_title | 2 | data_masking_overview, **gdpr_ccpa_compliance**, data_masking_overview |
| q3: "How do I anonymize a mailing address..." | address_ip_national_id_mask.md | vocab_divergent | 1 | address_ip_national_id_mask, masking_functions_overview, masking_functions_overview |
| q4: "What parameters does EMAIL_MASK accept..." | email_mask.md | near_title | 3 | masking_functions_overview, masking_functions_overview, **email_mask** |
| q5: "...column needs review and won't run..." | masking_troubleshooting.md | vocab_divergent | 2 | configuring_masking_jobs, **masking_troubleshooting**, masking_troubleshooting |
| q6: "...faster on hundreds of millions of rows..." | masking_performance_tuning.md | vocab_divergent | 1 | masking_performance_tuning, masking_performance_tuning, masking_troubleshooting |
| q7: "...function for a Social Security Number column..." | phone_ssn_mask.md | near_title | 1 | phone_ssn_mask, masking_functions_overview, masking_functions_overview |
| q8: "...schedule a masking job...every night..." | configuring_masking_jobs.md | vocab_divergent | 1 | configuring_masking_jobs, masking_troubleshooting, masking_performance_tuning |
| q9: "...checksum validity of credit card numbers..." | credit_card_account_mask.md | vocab_divergent | 1 | credit_card_account_mask, credit_card_account_mask, masking_functions_overview |
| q10: "...replacement values...masking a person's name..." | name_randomize.md | vocab_divergent | 2 | data_masking_overview, **name_randomize**, masking_functions_overview |

5 of 10 queries hit at rank 1; the rest still land within the top 3.
`masking_functions_overview.md` shows up as a frequent second/third-place
distractor -- expected, since it's an index-like doc that touches every
function by name and is semantically close to nearly every function-doc
query without being the *specific* answer.

## Known weak point (q4)

`email_mask.md` for the "what parameters does EMAIL_MASK accept" query
only reaches rank 3, behind two `masking_functions_overview.md` chunks.
Root cause: `masking_functions_overview.md`
mentions "EMAIL_MASK" by name in its function table, which gives it a real
BM25 signal on this query, while `email_mask.md`'s own `#parameters` chunk
is short and parameter-table-heavy with less prose overlap with the query's
wording. This still passes Recall@3 at the document level, but a
chunk-level metric (does the *specific* Parameters chunk rank #1) would
fail here. Not fixed -- flagged as a real, measured limitation rather than
tuned away, since tuning against a 10-query eval set risks fitting the
metric rather than improving retrieval generally (the same test-set-fitting
risk raised about RRF's `k` constant earlier).

## Honesty caveats on the 1.00

Two reasons this number should be read as "hybrid retrieval works," not as
"retrieval is solved":

1. **Query/corpus independence is weak.** Both `rag/corpus/*.md` and
   `masking_queries.json` were written with full knowledge of each other's
   content in the same session. Even the queries tagged `vocab_divergent`
   were chosen by someone who already knew what the target document says --
   a real customer's phrasing has no such constraint and could diverge
   further than anything tested here.
2. **Recall@3 over 12 documents is an easier bar than Recall@3 over a
   production-scale corpus.** With only 12 candidate documents, both BM25
   and vector search have a small space to get right. This number will not
   hold as-is once the corpus grows -- see SCALABILITY.md for what changes.

## Coverage gap

`data_masking_overview.md` and `masking_functions_overview.md` are not the
*expected* answer for any of the 10 queries (they appear only as
distractors). With 12 documents and 10 query slots, these two -- both
index/overview docs rather than actionable how-to content -- were
deprioritized in favor of covering all function-specific docs plus the
compliance/troubleshooting/performance/config docs the Day 3 agent is
actually tested against. Their retrieval quality is therefore unverified
by this eval set.
