# DATE_SHIFT

## DATE_SHIFT

### Usage

`DATE_SHIFT` replaces a sensitive date -- most commonly a date of birth --
with a different date, shifted by a random offset, rather than a fully
random replacement date. Shifting instead of fully randomizing preserves
*relative* time relationships within a record: if a customer's date of
birth and their account-opening date both get shifted by the same offset,
their age at account opening -- often a value downstream logic actually
depends on (age-gating, cohort analysis) -- stays correct after masking.

### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `max_shift_days` | integer | `365` | Maximum number of days a date can be shifted in either direction |
| `preserve_day_of_week` | boolean | `false` | If true, constrains the shift so the masked date falls on the same day of the week as the original |
| `consistent_offset_per_entity` | boolean | `true` | Applies the *same* shift offset to every date column belonging to the same record/entity, preserving relative gaps between dates on that record |
| `output_format` | string | `"YYYY-MM-DD"` | Format of the masked date |

### Examples

Input: `"1988-04-12"` with `max_shift_days: 365` -> Output: `"1988-09-03"`
(shifted forward 144 days)

With `consistent_offset_per_entity: true`, if `CUSTOMERS.date_of_birth` and
`CUSTOMERS.account_opened_date` both belong to the same customer row, both
dates shift by the identical offset -- so if the real gap between the two
was 9,862 days (27 years), the masked gap is still exactly 9,862 days, even
though both absolute dates are now fictitious.
