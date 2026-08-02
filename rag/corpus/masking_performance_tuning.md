# Masking Performance Tuning for Large Tables

## Performance Considerations

Masking throughput is dominated by two costs: per-value substitute
generation (cheap for format-based functions like `IP_MASK`, more
expensive for functions that draw from a lookup table like
`NAME_RANDOMIZE` or `ADDRESS_RANDOMIZE`) and, when `consistent_mapping` is
enabled, mapping-state lookups to check whether a value has already been
assigned a substitute earlier in the same job run.

For tables in the tens of millions of rows, the mapping-state lookup is
typically the larger cost, not the substitute generation itself -- a naive
mapping implementation that does a linear scan per value turns an
otherwise-linear job into a quadratic one.

## Batch Size and Parallelism

`batch_size` (see the job configuration reference) controls how many rows
are read, masked, and written per unit of work. Larger batches amortize
per-batch overhead (connection round-trips, transaction commits) but hold
more mapping state in memory at once. The default of 10,000 rows is a
reasonable starting point; tables over 50 million rows generally benefit
from raising `batch_size` to 50,000-100,000 provided the mapping-state
store can handle the larger in-memory working set.

Masking jobs parallelize at the table level by default -- independent
tables in the same job run mask concurrently. Within a single large table,
column-level masking is independent (no column's masked output depends on
another column's masked output, `consistent_offset_per_entity` in
`DATE_SHIFT` being the one exception, since it needs all of a record's date
columns available together) which makes row-range partitioning a safe way
to parallelize a single large table across workers.

## Indexing and Partitioning Strategies

When running in `copy_to` target mode, disable non-primary indexes on the
destination table before the masking job writes rows, and rebuild them
afterward -- index maintenance during a large bulk write is frequently the
single largest hidden cost in a masking job's total runtime, larger than
the masking computation itself.

For source tables partitioned by date or region, aligning `batch_size`
boundaries with partition boundaries avoids batches that span partitions,
which keeps each batch's read cost predictable and makes it straightforward
to resume a failed job from the last completed partition rather than
restarting the entire table from row zero.
