# Common Masking Errors and Troubleshooting

## Common Errors

**`ERR_UNRESOLVED_REVIEW_QUEUE`** -- The job's masking configuration
contains one or more columns with `review_required: true`. The job refuses
to run against those columns until a human reviewer resolves them (accept
the suggested function, pick an alternative, or mark not-PII). This is
intentional friction, not a bug -- see "Configuring and Running a Masking
Job" for why unresolved review items are a hard stop.

**`ERR_CHECKSUM_MISMATCH`** -- Raised by `CREDIT_CARD_MASK` when the
generated substitute fails its own Luhn validation before being written
out. This should not surface in normal operation; if it does, it usually
indicates the input value wasn't actually a well-formed card number to
begin with (a truncated or corrupted sample), and the column's
classification should be re-checked rather than the masking function
retried.

**`ERR_FOREIGN_KEY_DRIFT`** -- Raised when `consistent_mapping: true` is
set but the same source value produced two different masked outputs across
tables within one job run. This indicates a job configuration issue (two
separate job runs were used instead of one job covering both tables) --
consistent mapping is only guaranteed within a single job run, not across
runs.

## Diagnosing Masking Failures

Start with the job run log, not the target table. Every job records a
per-column outcome (masked, skipped-for-review, errored) with a reason
string. A silently wrong-looking masked value is almost always a
misclassified column upstream in PII detection, not a masking function
defect -- check the detection confidence and category that was assigned to
that column before assuming the masking function itself is at fault.

## FAQ

*Why did a column I expected to be masked show up unmasked in the output?*
Most commonly, the column was below the auto-configure confidence
threshold and landed in the review queue instead of `masking_rules` -- an
unmasked review-queue column is expected behavior, not a failure.

*Can I re-run a job and get the same masked values as last time?*
Only if `consistent_mapping` was enabled and you re-run within logic that
reuses the same job's mapping state. A fresh job run with no persisted
mapping will generate different substitute values -- this is by design,
since persisting mappings across runs would weaken the deidentification
guarantee described in the GDPR/CCPA compliance guide.
