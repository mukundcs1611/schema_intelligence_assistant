# Masking Functions Overview

## Available Masking Functions

The platform ships ten built-in masking functions, each targeting a specific
category of personal data. Every function takes a raw value and a set of
parameters, and returns a masked value of the same general shape.

| Function | Target data |
|---|---|
| NAME_RANDOMIZE | Person full names |
| EMAIL_MASK | Email addresses |
| PHONE_MASK | Phone numbers |
| SSN_MASK | Social Security Numbers |
| CREDIT_CARD_MASK | Credit card numbers |
| ACCOUNT_MASK | Bank / financial account numbers |
| DATE_SHIFT | Dates of birth and other sensitive dates |
| ADDRESS_RANDOMIZE | Postal / mailing addresses |
| IP_MASK | IP addresses |
| NATIONAL_ID_MASK | National ID and passport numbers |

## Choosing the Right Function

Function selection should follow the detected PII category, not the raw
column data type. Two columns can both be `VARCHAR(20)` and still need
completely different masking treatment -- one might be a phone number, the
other an account identifier. Matching on category, not type, is what keeps
the masked output format-consistent with what downstream consumers expect.

A general rule of thumb: if a value has an external format standard (email
addresses, IP addresses, national ID numbers), prefer a function that
preserves that standard's shape. If a value is free-form (a person's name,
a street address), prefer a function that generates a plausible replacement
rather than merely redacting characters -- plausible fakes catch more bugs
in downstream code that assumes well-formed data.

## Function Selection by PII Category

| Detected Category | Recommended Function |
|---|---|
| FULL_NAME | NAME_RANDOMIZE |
| EMAIL | EMAIL_MASK |
| PHONE | PHONE_MASK |
| SSN | SSN_MASK |
| CREDIT_CARD | CREDIT_CARD_MASK |
| ACCOUNT_NUMBER | ACCOUNT_MASK |
| DATE_OF_BIRTH | DATE_SHIFT |
| ADDRESS | ADDRESS_RANDOMIZE |
| IP_ADDRESS | IP_MASK |
| NATIONAL_ID | NATIONAL_ID_MASK |

This mapping is the same one the Schema Intelligence Assistant applies
automatically when it recommends a masking function for a detected column --
see the individual function pages for parameters and examples.
