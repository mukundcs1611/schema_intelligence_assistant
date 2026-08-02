# EMAIL_MASK

## EMAIL_MASK

### Usage

`EMAIL_MASK` replaces an email address with a synthetic address that keeps
a valid email shape (`local-part@domain.tld`), so that downstream
validation logic, deduplication keys, and format checks continue to behave
correctly against masked data.

By default the domain is replaced with a fixed synthetic domain
(`example-masked.com`) rather than randomized, since many test suites and
QA environments assert on a known domain pattern to distinguish masked
test accounts from real ones.

### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `domain` | string | `"example-masked.com"` | Domain used for all masked addresses |
| `preserve_domain` | boolean | `false` | If true, keeps the original domain and only randomizes the local part -- useful when downstream logic keys off domain (e.g. corporate vs. free-mail routing) |
| `consistent_mapping` | boolean | `true` | Same input email always maps to the same output email within a job |

### Examples

Input: `"user@example.com"` -> Output: `"x7f2ab@example-masked.com"`

Input: `"jane.doe@acmecorp.com"` with `preserve_domain: true` -> Output:
`"q93kdl@acmecorp.com"`

`consistent_mapping` matters here for the same reason it matters in
`NAME_RANDOMIZE`: if `CUSTOMERS.email` and `SUPPORT_TICKETS.reporter_email`
both contain the same real address, masking must produce the same
substitute in both places, or joins between those tables break after
masking.
