# What Is Data Masking

## Overview

Data masking is the process of replacing sensitive values in a dataset with
realistic-but-fictitious substitutes, so that the resulting data preserves
the shape, format, and statistical properties of the original while no
longer exposing the real values. Masked data can be safely used in lower
environments -- development, QA, staging, analytics sandboxes, and
third-party integrations -- without exposing production personal data.

Masking is distinct from access control: it does not restrict *who* can see
a dataset, it changes *what* they see. A developer with full read access to
a masked customer table can query it freely, run joins, build reports, and
reproduce bugs, without ever touching a real name, email, or account number.

## Why Enterprises Use Data Masking

Three recurring drivers show up across customer deployments:

- **Regulatory obligation.** Frameworks such as GDPR and CCPA restrict how
  personal data may be processed and shared, including internally between
  teams and environments. Masking lets non-production environments exist
  without falling under the same handling restrictions as production.
- **Breach blast-radius reduction.** A leaked or misconfigured staging
  database is a routine incident category. If the data in that environment
  is masked, the incident's severity drops sharply because there is no real
  personal data to disclose.
- **Vendor and contractor data sharing.** Enterprises frequently need to
  hand a realistic dataset to an external QA vendor, a consulting partner,
  or an analytics contractor. Masked data satisfies "realistic enough to be
  useful" without a data processing agreement covering the real records.

## Masking vs. Encryption vs. Tokenization

These three are often confused, but they solve different problems:

| Technique | Reversible? | Preserves format? | Typical use |
|---|---|---|---|
| Encryption | Yes, with key | Not usually | Data at rest / in transit protection |
| Tokenization | Yes, via token vault | Yes | Payment data, systems needing round-trip |
| Masking | No (one-way) | Yes | Non-production environments, analytics, sharing |

Masking in this platform is deliberately one-way: once a column is masked,
the original value is not recoverable from the masked output. This is a
design choice, not a limitation -- non-production environments should never
need to reverse a masked value back to the real one.
