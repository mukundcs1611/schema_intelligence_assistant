"""Turns Day 1 detection results into a masking job configuration -- the
artifact that replaces the "3-4 days per customer manually reviewing
schemas" pain point from the task scenario.

Pure transformation, no LLM call and no RAG query at generation time --
documentation_reference is a static lookup, not a search (see conversation
around rag/ingest.py's anchor scheme for why the anchors below are what
they are).
"""
from datetime import date
from typing import Optional

# category -> "<corpus file>#<anchor>", matching the chunk_id scheme
# rag/ingest.py actually produces (verified against rag/index/chunks.json,
# not hand-guessed) -- keep these two in sync if the corpus headings change.
PII_CATEGORY_TO_DOC_REFERENCE = {
    "FULL_NAME": "name_randomize.md#name_randomize-usage",
    "EMAIL": "email_mask.md#email_mask-usage",
    "PHONE": "phone_ssn_mask.md#phone_mask-usage",
    "SSN": "phone_ssn_mask.md#ssn_mask-usage",
    "CREDIT_CARD": "credit_card_account_mask.md#credit_card_mask-usage",
    "ACCOUNT_NUMBER": "credit_card_account_mask.md#account_mask-usage",
    "DATE_OF_BIRTH": "date_shift.md#date_shift-usage",
    "ADDRESS": "address_ip_national_id_mask.md#address_randomize-usage",
    "IP_ADDRESS": "address_ip_national_id_mask.md#ip_mask-usage",
    "NATIONAL_ID": "address_ip_national_id_mask.md#national_id_mask-usage",
}

# category -> masking function, duplicated from pii_patterns.MASKING_FUNCTION_MAP
# rather than imported, so this module has no import-path dependency on
# pii-detector/ being on sys.path -- these ten pairs are part of the JD's
# fixed contract, not expected to drift independently of that spec.
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


class MaskingConfigGenerator:
    def generate(self, detections: list) -> dict:
        masking_rules = []
        review_queue = []
        auto_configured = requires_review = not_pii = 0

        for d in detections:
            if d.is_pii and not d.review_required:
                auto_configured += 1
                masking_rules.append({
                    "table": d.table,
                    "column": d.column,
                    "masking_function": d.recommended_masking_function,
                    "parameters": {},
                    "confidence": d.confidence,
                    "requires_review": False,
                    "documentation_reference": PII_CATEGORY_TO_DOC_REFERENCE.get(d.pii_category),
                })

            elif d.review_required:
                requires_review += 1
                alt_category = getattr(d, "alternative_category", None)
                if d.is_pii:
                    reason = f"Low confidence ({d.confidence:.2f}) -- {d.reasoning}"
                    suggested_function = d.recommended_masking_function
                else:
                    # Case 3d/e's own extension: an ungrounded low-confidence
                    # "not PII" call doesn't get to silently clear either --
                    # see detector.py's NEGATIVE_REVIEW_FLOOR. No category,
                    # so no suggested function and no alternatives to offer.
                    reason = (
                        f"Low confidence not-PII ({d.confidence:.2f}) -- "
                        f"flagged for review rather than silently cleared. {d.reasoning}"
                    )
                    suggested_function = None
                alternatives = [MASKING_FUNCTION_MAP[alt_category]] if alt_category else []
                review_queue.append({
                    "table": d.table,
                    "column": d.column,
                    "reason": reason,
                    "suggested_function": suggested_function,
                    "alternatives": alternatives,
                })

            else:
                not_pii += 1

        return {
            "masking_job_name": f"AUTO_GENERATED_{date.today().isoformat()}",
            "generated_by": "SchemaIntelligenceAssistant",
            "confidence_summary": {
                "auto_configured": auto_configured,
                "requires_review": requires_review,
                "not_pii": not_pii,
            },
            "masking_rules": masking_rules,
            "review_queue": review_queue,
        }
