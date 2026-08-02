# CREDIT_CARD_MASK and ACCOUNT_MASK

## CREDIT_CARD_MASK

### Usage

`CREDIT_CARD_MASK` replaces a credit card number with a synthetic number
that passes the Luhn checksum, so that any downstream code validating card
number well-formedness (a common pattern in checkout and billing test
suites) continues to pass against masked data. The card network prefix
(Visa `4`, Mastercard `5`, etc.) is preserved by default so BIN-based
routing logic in QA environments keeps behaving the same way.

### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `preserve_network_prefix` | boolean | `true` | Keeps the card network's leading digit(s) intact |
| `preserve_last_four` | boolean | `true` | Keeps last four digits unmasked -- matches typical "ending in 1234" display UX |
| `consistent_mapping` | boolean | `true` | Same input card number maps to the same output within a job |

### Examples

Input: `"4111 1111 1111 1234"` -> Output: `"4111 9284 7710 1234"` (Visa
prefix and last four preserved, middle digits randomized, Luhn-valid)

Input: `"****-****-****-1234"` (already display-masked) -> Output:
`"****-****-****-1234"` unchanged -- the function detects an already-masked
value and passes it through rather than attempting to re-mask a value that
carries no real digits to protect.

## ACCOUNT_MASK

### Usage

`ACCOUNT_MASK` replaces a bank or financial account number with a
synthetic identifier of the same length and character class (numeric,
alphanumeric, or prefixed format like `ACC-98765`). Unlike
`CREDIT_CARD_MASK`, there is no universal checksum standard for account
numbers, so this function does not attempt one -- format preservation is
the only correctness guarantee.

### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `preserve_prefix` | boolean | `true` | Keeps any non-numeric prefix (e.g. `"ACC-"`, `"IBAN"`) intact |
| `preserve_length` | boolean | `true` | Output has the same character length as input |
| `consistent_mapping` | boolean | `true` | Same input account number maps to the same output within a job |

### Examples

Input: `"ACC-98765"` -> Output: `"ACC-40217"`

Input: `"****1234"` -> Output: `"****7790"`
