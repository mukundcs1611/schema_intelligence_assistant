# NAME_RANDOMIZE

## NAME_RANDOMIZE

### Usage

`NAME_RANDOMIZE` replaces a person's full name with a synthetic name drawn
from a locale-aware name table, rather than redacting or scrambling the
original characters. This keeps downstream systems that validate "looks
like a real name" (form validation, search indexing, fuzzy-match testing)
working correctly against masked data.

Apply this function to any column classified as `FULL_NAME` -- first name,
last name, and combined full-name columns are all supported; the function
detects which shape it received from the input value's structure.

### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `locale` | string | `en_US` | Name table to draw substitutes from (e.g. `en_US`, `es_ES`, `fr_FR`) |
| `preserve_gender` | boolean | `true` | If true, replacement name matches the inferred gender of the original |
| `consistent_mapping` | boolean | `true` | If true, the same input name always maps to the same output name within a masking job, preserving referential joins across tables |
| `format` | string | `"first last"` | Output name shape: `"first last"`, `"last, first"`, or `"first"` |

### Examples

Input: `"Priya Sharma"` -> Output: `"Devika Nair"` (locale `en_US` with an
Indian name table extension, gender preserved)

Input: `"Daniel Wu"` -> Output: `"Marcus Feld"`

With `consistent_mapping: true`, every row across every table where
`"Priya Sharma"` appears as a value in a `FULL_NAME`-classified column
resolves to the same `"Devika Nair"` substitute, which keeps foreign-key
relationships between an `EMPLOYEES` table and an `ORDERS.sales_rep` column
intact after masking.
