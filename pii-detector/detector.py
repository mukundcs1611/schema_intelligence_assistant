"""Hybrid PII column classifier: rule engine (Layer 1) + LLM (Layer 2).

Layer 2 is only called when Layer 1 is inconclusive -- see _score_rule_layer
for exactly what "inconclusive" means. This keeps LLM cost proportional to
schema ambiguity, not schema size (SCALABILITY.md).

Confidence blending, in precedence order (see README.md / conversation log
for the reasoning behind each case -- this table is the spec, not an
afterthought):

  1. Rule score >= 0.90 (name AND sample both match)        -> skip LLM.
  2. No rule match, name is a known-safe operational field   -> skip LLM, not PII, 0.95.
  3. Escalated to LLM:
     a. Rule has a category, LLM agrees                      -> 0.3*rule + 0.7*llm
     b. No rule category, LLM says PII                       -> min(llm, 0.85)   [capped: no corroboration]
     c. Rule has a category, LLM disagrees (or says not-PII) -> True, min(llm_or_rule, 0.70) [conflict -> always review]
     d. No rule category, LLM says not-PII, conf >= 0.60     -> not PII, llm confidence as-is
     e. No rule category, LLM says not-PII, conf < 0.60      -> not PII, but review_required=True anyway

Cases (c) and (e) are deliberate extensions past the literal JSON contract,
in the direction QUALITY_CRITERIA.md's recall/precision asymmetry demands:
disagreement never silently resolves to "not PII", and an ungrounded
low-confidence "not PII" doesn't get to hide either.
"""
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import ollama
from dotenv import load_dotenv

from pii_patterns import (
    MASKING_FUNCTION_MAP,
    is_generic_non_pii_name,
    name_matches,
    sample_matches,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from audit_logger import AuditLogger  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

CLASSIFIER_MODEL = os.environ.get("CLASSIFIER_MODEL", "qwen2.5:7b")
AUTO_CONFIGURE_THRESHOLD = float(os.environ.get("AUTO_CONFIGURE_THRESHOLD", "0.80"))
NEGATIVE_REVIEW_FLOOR = float(os.environ.get("NEGATIVE_REVIEW_FLOOR", "0.60"))
PII_CATEGORIES = list(MASKING_FUNCTION_MAP.keys())

RULE_ALONE_THRESHOLD = 0.90
NO_CORROBORATION_CAP = 0.85
CONFLICT_CAP = 0.70

SYSTEM_PROMPT = f"""You are a PII classification engine for a database schema tool. A
rule-based layer has already tried to classify this column and could not
resolve it confidently -- that is why you are being asked.

Categories: {", ".join(PII_CATEGORIES)}.

Rules:
- Numeric identifiers used only as internal record keys (order_id, transaction_id, product_id) are NOT PII.
- Company/organization names are NOT PII. FULL_NAME is for individual persons only.
- Dates that are not a person's birth date (e.g. ship_date, created_at, order_date) are NOT PII.
- sample_values are your primary evidence for what the column actually stores.
  column_name is a hint, not proof -- do not classify based on the name alone
  when sample values are present and legible.
- When a column name describes a relationship or role rather than a data type
  (e.g. "next_of_kin", "emergency_contact", "beneficiary", "referred_by"),
  that name tells you WHO the value is relative to, not WHAT the value is.
  Look at the sample values: if they are themselves a person's name, the
  column is FULL_NAME regardless of what relationship its name implies.
- If genuinely uncertain, lower the confidence rather than guessing high.

Respond with strict JSON only:
{{"is_pii": <bool>, "pii_category": <one of the categories above, or null>, "confidence": <float 0-1>, "reasoning": "<one sentence>", "suggested_rule_keyword": <string or null>}}

suggested_rule_keyword: if is_pii is true and the column name contains a term
a keyword dictionary should have caught but didn't (a synonym, abbreviation,
or non-English word for the category), return it in lowercase,
underscore-separated form. If the column name is too generic/ambiguous to
turn into a safe standing rule (e.g. "ref_code", "fld_23"), return null --
do not propose rules that would create false positives on other columns.
"""


@dataclass
class DetectionResult:
    table: str
    column: str
    is_pii: bool
    confidence: float
    pii_category: Optional[str]
    recommended_masking_function: Optional[str]
    review_required: bool
    reasoning: str = ""


class PiiDetector:
    def __init__(
        self,
        model: str = CLASSIFIER_MODEL,
        client: "ollama.Client | None" = None,
        audit_logger: Optional[AuditLogger] = None,
    ):
        self.model = model
        self.client = client or ollama
        # Every detect() call writes one row here -- README.md's design
        # decision #4 ("every decision is logged to audit storage"), which
        # wasn't actually true until this got wired in. Pass a custom
        # AuditLogger(db_path=...) to point at a scratch DB in tests.
        self.audit_logger = audit_logger or AuditLogger()

    # -- Layer 1 --------------------------------------------------------
    def _score_rule_layer(self, column: dict):
        name = column["column_name"]
        samples = column.get("sample_values", [])
        best_category, best_score = None, 0.0
        for category in PII_CATEGORIES:
            nm = name_matches(name, category)
            sm = sample_matches(samples, category)
            if not nm and not sm:
                continue
            score = 0.97 if (nm and sm) else 0.60 if nm else 0.55
            if score > best_score:
                best_category, best_score = category, score
        return best_category, best_score

    # -- Layer 2 ----------------------------------------------------------
    def _llm_classify(self, column: dict, rule_category: Optional[str]) -> dict:
        user_prompt = (
            f"table_name: {column['table_name']}\n"
            f"column_name: {column['column_name']}\n"
            f"data_type: {column['data_type']}\n"
            f"sample_values: {column.get('sample_values', [])}\n"
            f"nullable: {column.get('nullable')}\n"
            f"rule_layer_opinion: {rule_category or 'none'}\n"
        )
        try:
            response = self.client.chat(
                model=self.model,
                format="json",
                options={"temperature": 0},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )
            parsed = json.loads(response["message"]["content"])
            return {
                "is_pii": bool(parsed.get("is_pii", False)),
                "pii_category": parsed.get("pii_category"),
                "confidence": float(parsed.get("confidence", 0.5)),
                "reasoning": parsed.get("reasoning", ""),
                "suggested_rule_keyword": parsed.get("suggested_rule_keyword"),
            }
        except Exception as exc:  # model unreachable, malformed JSON, etc.
            return {
                "is_pii": False,
                "pii_category": None,
                "confidence": 0.0,
                "reasoning": f"LLM classification unavailable ({exc}); rule layer only.",
                "suggested_rule_keyword": None,
            }

    def _blend(self, rule_category, rule_score, llm: dict):
        """Returns (is_pii, category, confidence, reasoning, suggested_rule_keyword).
        The keyword is only ever non-null when llm_is_pii -- see the prompt's
        own instruction not to propose rules off a negative classification.
        """
        llm_is_pii = llm["is_pii"]
        llm_category = llm["pii_category"]
        llm_confidence = llm["confidence"]
        suggested_keyword = llm.get("suggested_rule_keyword") if llm_is_pii else None

        # Case 3a: rule has a category, LLM agrees
        if rule_category and llm_is_pii and llm_category == rule_category:
            confidence = round(0.30 * rule_score + 0.70 * llm_confidence, 2)
            return True, rule_category, confidence, llm["reasoning"], suggested_keyword

        # Case 3b: no rule category, LLM says PII -- capped, no corroboration
        if not rule_category and llm_is_pii:
            confidence = round(min(llm_confidence, NO_CORROBORATION_CAP), 2)
            return True, llm_category, confidence, llm["reasoning"], suggested_keyword

        # Case 3c: rule has a category, LLM disagrees (category or is_pii) -- conflict, never silently clears
        if rule_category and (not llm_is_pii or llm_category != rule_category):
            if llm_is_pii:
                confidence = round(min(llm_confidence, CONFLICT_CAP), 2)
                reasoning = (
                    f"Rule layer suggested {rule_category}, LLM suggested {llm_category}; "
                    f"conflicting signals, routed to review. {llm['reasoning']}"
                )
                return True, llm_category, confidence, reasoning, suggested_keyword
            confidence = round(min(rule_score, CONFLICT_CAP), 2)
            reasoning = (
                f"Rule layer matched {rule_category} but LLM disagreed; "
                f"routed to review pending human judgement. {llm['reasoning']}"
            )
            return True, rule_category, confidence, reasoning, None

        # Case 3d/3e: no rule category, LLM says not-PII
        return False, None, round(llm_confidence, 2), llm["reasoning"], None

    def detect(self, column: dict) -> dict:
        rule_category, rule_score = self._score_rule_layer(column)

        if rule_category and rule_score >= RULE_ALONE_THRESHOLD:
            is_pii, category, confidence, reasoning, source, suggested_keyword = (
                True, rule_category, rule_score,
                f"Column name and sample values both match the {rule_category} pattern (rule layer, no LLM call needed).",
                "rule_strong", None,
            )
        elif rule_category is None and is_generic_non_pii_name(column["column_name"]):
            is_pii, category, confidence, reasoning, source, suggested_keyword = (
                False, None, 0.95,
                "Column name matches a common non-PII operational field pattern; no LLM call needed.",
                "rule_safe_list", None,
            )
        else:
            llm_result = self._llm_classify(column, rule_category)
            is_pii, category, confidence, reasoning, suggested_keyword = self._blend(rule_category, rule_score, llm_result)
            source = "llm_blend"

        if is_pii:
            review_required = confidence < AUTO_CONFIGURE_THRESHOLD
        else:
            review_required = rule_category is None and confidence < NEGATIVE_REVIEW_FLOOR

        masking_function = MASKING_FUNCTION_MAP.get(category) if is_pii else None

        self.audit_logger.log_decision(
            table_name=column["table_name"],
            column_name=column["column_name"],
            is_pii=is_pii,
            pii_category=category,
            confidence=confidence,
            recommended_masking_function=masking_function,
            review_required=review_required,
            reasoning=reasoning,
            source=source,
            suggested_rule_keyword=suggested_keyword,
        )

        return {
            "is_pii": is_pii,
            "confidence": confidence,
            "pii_category": category,
            "recommended_masking_function": masking_function,
            "review_required": review_required,
            "reasoning": reasoning,
        }

    def detect_all(self, schema: list[dict]) -> list[DetectionResult]:
        results = []
        for column in schema:
            r = self.detect(column)
            results.append(DetectionResult(
                table=column["table_name"],
                column=column["column_name"],
                is_pii=r["is_pii"],
                confidence=r["confidence"],
                pii_category=r["pii_category"],
                recommended_masking_function=r["recommended_masking_function"],
                review_required=r["review_required"],
                reasoning=r["reasoning"],
            ))
        return results
