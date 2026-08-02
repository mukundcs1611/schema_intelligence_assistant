# ADDRESS_RANDOMIZE, IP_MASK, and NATIONAL_ID_MASK

## ADDRESS_RANDOMIZE

### Usage

`ADDRESS_RANDOMIZE` replaces a postal or mailing address with a synthetic
address that remains geographically plausible -- the substitute is drawn
from a real street-name and city table so it passes basic address
validation (a real-looking street, a real city/state/postal-code
combination) without pointing at the customer's actual location.

### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `preserve_country` | boolean | `true` | Keeps the original country, randomizes everything below it |
| `preserve_postal_region` | boolean | `false` | If true, keeps the same postal code region (e.g. same US state) to preserve geography-dependent test logic |
| `consistent_mapping` | boolean | `true` | Same input address maps to the same output within a job |

### Examples

Input: `"742 Evergreen Terrace, Springfield, IL 62704"` -> Output:
`"118 Birchwood Ave, Rockford, IL 61101"` (state preserved via
`preserve_postal_region: true`)

## IP_MASK

### Usage

`IP_MASK` replaces an IP address with a synthetic address of the same
version (IPv4 or IPv6). By default it preserves the network portion of the
address (the leading octets) and randomizes only the host portion, since
many downstream systems use IP ranges for geolocation or network-tier
logic that would otherwise break entirely on a fully random address.

### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `preserve_network_bits` | integer | `16` | Number of leading bits preserved from the original address |
| `consistent_mapping` | boolean | `true` | Same input IP maps to the same output within a job |

### Examples

Input: `"203.0.113.42"` with `preserve_network_bits: 16` -> Output:
`"203.0.184.221"`

## NATIONAL_ID_MASK

### Usage

`NATIONAL_ID_MASK` replaces a national identification number -- passport
number, national insurance number, Aadhaar, or similar -- with a synthetic
value in the same format. Because national ID formats vary widely by
country (alphanumeric passport codes vs. purely numeric IDs), this function
detects the input's character-class pattern and generates a substitute
matching it, rather than assuming a single fixed format.

### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `country_hint` | string | `null` | Optional ISO country code to select a country-specific format table; if omitted, format is inferred from the input pattern |
| `preserve_length` | boolean | `true` | Output has the same character length as input |
| `consistent_mapping` | boolean | `true` | Same input ID maps to the same output within a job |

### Examples

Input: `"AB123456C"` (UK National Insurance format) -> Output:
`"CD778213F"`

Input: `"234198765432"` (Aadhaar-style 12-digit numeric) -> Output:
`"981204476651"`
