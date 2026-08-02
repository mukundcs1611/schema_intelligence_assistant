# Configuring and Running a Masking Job

## Creating a Masking Job

A masking job is the unit of work that applies a set of masking rules to a
target database or set of tables. A job is defined by a masking
configuration document -- the same JSON structure the Schema Intelligence
Assistant produces automatically from PII detection results -- specifying,
per column, which masking function to apply and with what parameters.

At minimum a job needs: a source connection, a target (either the same
database with an in-place update, or a separate destination for a
copy-and-mask workflow), and the masking configuration document.

## Job Configuration Reference

| Field | Required | Description |
|---|---|---|
| `masking_job_name` | Yes | Unique identifier for the job, used in logs and the audit trail |
| `source_connection` | Yes | Connection string or reference to the database being masked |
| `target_mode` | Yes | `in_place` or `copy_to` -- whether masking overwrites the source or writes to a new destination |
| `masking_rules` | Yes | List of table/column/function/parameter entries |
| `review_queue` | No | Columns flagged for human review before the job includes them; a job will refuse to run against `review_required: true` columns until they are resolved |
| `batch_size` | No | Number of rows processed per batch, default 10,000 (see the performance tuning guide for large-table guidance) |

## Running and Scheduling Jobs

Jobs can be run ad hoc via the CLI (`maskctl run <job-name>`) or scheduled
on a recurring cadence, most commonly nightly, to keep a staging or QA
environment's masked copy in sync with a periodically refreshed production
snapshot.

A job that encounters a column with `review_required: true` in its
configuration will halt before touching that column and surface it in the
run log, rather than silently skipping it or applying a default guess --
unresolved review-queue items are a hard stop, not a warning.

## Monitoring Job Status

Every job run writes a summary record: rows processed, columns masked,
elapsed time, and any columns skipped due to unresolved review status. This
summary feeds the same audit trail infrastructure used for individual
column-level masking decisions, giving a single place to answer "was table
X masked, when, and with what configuration" for compliance reporting.
