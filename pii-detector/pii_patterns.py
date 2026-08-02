"""Layer 1: free, deterministic rule signals for PII detection.

Three independent signal sources, combined by detector.py:
  1. Name keywords  -- does the column name match a known term for a category?
  2. Value patterns  -- do the sample values match the category's format?
  3. Checksums       -- for formats that have one (credit card, IBAN), does the
                        sample value actually pass it? This is a free precision
                        booster: a 16-digit string that fails Luhn is very
                        unlikely to be a real card number.

Nothing here calls an LLM or does anything probabilistic -- every function is
pure and auditable, which is the point of Layer 1.
"""
import re
from pathlib import Path

import yaml

MASKING_FUNCTION_MAP = {
    "FULL_NAME": "NAME_RANDOMIZE",
    "EMAIL": "EMAIL_MASK",
    "PHONE": "PHONE_MASK",
    "SSN": "SSN_MASK",
    "CREDIT_CARD": "CREDIT_CARD_MASK",
    "ACCOUNT_NUMBER": "ACCOUNT_MASK",
    "DATE_OF_BIRTH": "DATE_SHIFT",
    "ADDRESS": "ADDRESS_RANDOMIZE",
    "IP_ADDRESS": "IP_MASK",
    "NATIONAL_ID": "NATIONAL_ID_MASK",
}

# Positive name signals. Matched as whole tokens after splitting the column
# name on non-alphanumeric characters, or as a substring of the
# underscore-joined name (so multi-word keywords like "date_of_birth" work).
# Includes a few non-English variants -- QUALITY_CRITERIA.md commits to that
# edge case and the rule layer needs to carry some of that weight itself,
# not defer everything to the LLM.
POSITIVE_NAME_KEYWORDS = {
    "FULL_NAME": [
        "name", "fullname", "full_name", "first_name", "last_name",
        "customer_name", "contact_name", "employee_name", "cust_name",
        "nome", "nome_completo", "nombre", "prenom", "nom",
    ],
    "EMAIL": ["email", "e_mail", "mail", "email_address", "mail_address", "correo", "courriel"],
    "PHONE": ["phone", "mobile", "telephone", "tel", "cell", "contact_no", "phone_number", "telefono", "telefone"],
    "SSN": ["ssn", "social_security", "social_sec", "social_security_number"],
    "CREDIT_CARD": ["credit_card", "creditcard", "card_no", "card_number", "cc_number", "cc_no", "pan"],
    "ACCOUNT_NUMBER": ["account", "acct", "account_no", "account_number", "acct_no", "iban", "routing_number"],
    "DATE_OF_BIRTH": ["dob", "date_of_birth", "birth_date", "birthdate", "dateofbirth", "fecha_nacimiento"],
    "ADDRESS": ["address", "street", "addr", "mailing_address", "home_address", "direccion", "adresse"],
    "IP_ADDRESS": ["ip", "ip_address", "ipaddress", "client_ip", "src_ip", "remote_addr"],
    "NATIONAL_ID": [
        "national_id", "nationalid", "passport", "passport_no", "national_insurance",
        "national_insurance_number", "nin", "tax_id", "ni_number", "sin", "aadhaar",
    ],
}

# Negative signals: block a category match even if a positive keyword hit.
# Keeps "company_name" out of FULL_NAME and "ship_date" out of DATE_OF_BIRTH.
NEGATIVE_NAME_KEYWORDS = {
    "FULL_NAME": [
        "company", "business", "org", "organization", "vendor", "brand",
        "product", "file", "table", "schema", "database", "username", "login",
    ],
    "DATE_OF_BIRTH": [
        "ship", "created", "updated", "modified", "order", "expiry",
        "expires", "start", "end", "due", "hire", "termination",
    ],
}

# Known-safe operational fields. If the name matches one of these and nothing
# else, skip the LLM entirely -- this is the actual cost-control lever
# (SCALABILITY.md's "80% resolve at Layer 1" claim rests on this list).
GENERIC_NON_PII_TOKENS = {
    "id", "quantity", "qty", "amount", "price", "count", "status", "flag",
    "type", "category", "description", "desc", "timestamp", "url", "link",
    "hash", "uuid", "version", "currency", "sku", "inventory", "warehouse",
    "created_at", "updated_at", "modified_at", "created", "updated",
    "product", "order", "transaction", "invoice", "session", "request",
    "total", "subtotal", "tax", "discount", "rating", "score", "weight",
    "height", "width", "length", "color", "size", "department", "region",
}

VALUE_PATTERNS = {
    "EMAIL": re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
    "PHONE": re.compile(r"^\+?[\d][\d\-.\s()]{7,14}\d$"),
    "SSN": re.compile(r"^(\d{3}-\d{2}-\d{4}|[*Xx]{3}-[*Xx]{2}-\d{4})$"),
    "CREDIT_CARD": re.compile(r"^(\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}|\*{4}[\s-]?\*{4}[\s-]?\*{4}[\s-]?\d{4})$"),
    # No bare \d{6,12} alternative on purpose -- that would also match
    # transaction_id / order_id sample values. Account numbers here must
    # carry a distinguishing prefix or a masking pattern.
    "ACCOUNT_NUMBER": re.compile(r"^([A-Za-z]{2,4}-\d{4,10}|\*{2,8}\d{4})$"),
    "DATE_OF_BIRTH": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    "ADDRESS": re.compile(r"\d+\s+\w+.*\b(st|street|ave|avenue|rd|road|blvd|boulevard|ln|lane|dr|drive)\b", re.IGNORECASE),
    "IP_ADDRESS": re.compile(r"^(\d{1,3}\.){3}\d{1,3}$"),
    "NATIONAL_ID": re.compile(r"^[A-Z]{2}\d{6,9}[A-Z]?$"),
    "FULL_NAME": re.compile(r"^[A-Z][a-z]+([\s-][A-Z][a-z]+)+$"),
}

# Categories with a real checksum -- used as a free precision booster on top
# of the format regex. A 16-digit string that matches the CREDIT_CARD regex
# but fails Luhn is very unlikely to actually be a card number.
CHECKSUM_CATEGORIES = {"CREDIT_CARD"}

# Human-approved keywords, promoted from LLM suggestions via promote_rules.py.
# Merged on top of POSITIVE_NAME_KEYWORDS in name_matches() -- this dict
# above is never edited by the promotion flow, only read alongside it.
PROMOTED_RULES_PATH = Path(__file__).resolve().parent / "promoted_rules.yaml"
_promoted_cache = {"mtime": None, "data": {}}


def get_promoted_keywords(path: Path = None) -> dict:
    """Re-parses only if the file's mtime changed since the last call, so
    this is cheap enough to call on every name_matches() -- no explicit
    reload needed, an approval in promote_rules.py is picked up by the very
    next detect() call.

    path defaults to the live PROMOTED_RULES_PATH module global, resolved
    at call time rather than bound at import time -- lets tests monkeypatch
    PROMOTED_RULES_PATH to point at a temp file without needing to also
    reload this function's signature.
    """
    path = path or PROMOTED_RULES_PATH
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return {}
    if mtime != _promoted_cache["mtime"]:
        with open(path) as f:
            _promoted_cache["data"] = yaml.safe_load(f) or {}
        _promoted_cache["mtime"] = mtime
    return _promoted_cache["data"]


def tokenize(column_name: str) -> list[str]:
    return [t for t in re.split(r"[^a-zA-Z0-9]+", column_name.lower()) if t]


def name_matches(column_name: str, category: str) -> bool:
    # `joined` must preserve the original token order (a set's iteration
    # order is randomized per-process in Python, which made multi-word
    # keyword substring checks like "credit_card" in joined non-deterministic
    # across separate runs -- same column, different result depending on
    # process hash seed). token_list keeps order; the set is only for the
    # cheap whole-token membership check.
    token_list = tokenize(column_name)
    token_set = set(token_list)
    joined = "_".join(token_list)
    keywords = POSITIVE_NAME_KEYWORDS.get(category, []) + get_promoted_keywords().get(category, [])
    if not any(kw in token_set or kw in joined for kw in keywords):
        return False
    negatives = NEGATIVE_NAME_KEYWORDS.get(category, [])
    if any(neg in token_set or neg in joined for neg in negatives):
        return False
    return True


def _luhn_valid(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def passes_checksum(sample_value: str, category: str) -> bool:
    """True if the category has no checksum to check, OR the value passes it.
    False only means "this specific value failed a real checksum" -- callers
    should treat that as a strong negative signal, not just "unknown".
    """
    if category not in CHECKSUM_CATEGORIES:
        return True
    digits = re.sub(r"\D", "", sample_value)
    if category == "CREDIT_CARD":
        if "*" in sample_value:  # masked value, can't checksum, don't penalise
            return True
        if len(digits) not in (13, 15, 16):
            return True  # not a card-shaped value at all -- not this check's job
        return _luhn_valid(digits)
    return True


def sample_matches(sample_values: list[str], category: str) -> bool:
    pattern = VALUE_PATTERNS.get(category)
    if pattern is None:
        return False
    cleaned = [str(v).strip() for v in sample_values if v and str(v).strip().lower() != "null"]
    if not cleaned:
        return False
    format_hits = [v for v in cleaned if pattern.match(v)]
    if not format_hits:
        return False
    if category in CHECKSUM_CATEGORIES:
        return any(passes_checksum(v, category) for v in format_hits)
    return True


def is_generic_non_pii_name(column_name: str) -> bool:
    return bool(set(tokenize(column_name)) & GENERIC_NON_PII_TOKENS)
