# PHONE_MASK and SSN_MASK

## PHONE_MASK

### Usage

`PHONE_MASK` replaces a phone number with a synthetic number that preserves
country code and length, so downstream validation (e.g. "must be a 10-digit
US number") continues to pass. Formatting characters (dashes, parentheses,
spaces) in the original value are preserved in the output.

### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `preserve_country_code` | boolean | `true` | Keeps the original country/area code prefix, randomizes only the subscriber portion |
| `preserve_formatting` | boolean | `true` | Keeps original punctuation/spacing pattern |
| `consistent_mapping` | boolean | `true` | Same input number maps to the same output within a job |

### Examples

Input: `"+1-415-555-0198"` -> Output: `"+1-415-555-8823"`

Input: `"(212) 555-0134"` -> Output: `"(212) 555-4471"`

## SSN_MASK

### Usage

`SSN_MASK` replaces a Social Security Number with a synthetic number in the
same `XXX-XX-XXXX` format. Unlike `PHONE_MASK`, `SSN_MASK` never preserves
any digits from the original value by default -- SSNs carry no legitimate
downstream validation dependency on partial digit preservation the way
phone area codes sometimes do, so full randomization is the safer default.

### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `preserve_last_four` | boolean | `false` | If true, keeps the last four digits unmasked -- only enable this for environments that specifically test "last four digits" display logic |
| `output_format` | string | `"XXX-XX-XXXX"` | Format of the masked value; can also emit fully-masked display form `***-**-1234` |
| `consistent_mapping` | boolean | `true` | Same input SSN maps to the same output within a job |

### Examples

Input: `"523-11-4477"` -> Output: `"891-64-2038"`

Input: `"***-**-4477"` (already partially masked upstream) -> Output:
`"***-**-2038"` (last four re-randomized, masking pattern preserved)
