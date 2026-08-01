"""Day 1B tests. First four are verbatim from the task doc; test 5 is our own
addition because QUALITY_CRITERIA.md commits to a precision target the doc's
own test set doesn't check.

Run from pii-detector/: pytest tests/
"""
import json
from pathlib import Path

import pytest
from detector import PiiDetector

detector = PiiDetector()


def test_email_column_detected():
    result = detector.detect({
        "table_name": "USERS", "column_name": "email_address",
        "data_type": "VARCHAR(255)", "sample_values": ["user@example.com"], "nullable": True
    })
    assert result["is_pii"] is True
    assert result["pii_category"] == "EMAIL"
    assert result["recommended_masking_function"] == "EMAIL_MASK"


def test_non_pii_column_not_flagged():
    result = detector.detect({
        "table_name": "ORDERS", "column_name": "transaction_id",
        "data_type": "BIGINT", "sample_values": ["100001", "100002"], "nullable": False
    })
    assert result["is_pii"] is False


def test_low_confidence_sets_review_required():
    result = detector.detect({
        "table_name": "CONTRACTS", "column_name": "ref_code",
        "data_type": "VARCHAR(20)", "sample_values": ["C-2024-001"], "nullable": True
    })
    if result["confidence"] < 0.80:
        assert result["review_required"] is True


def test_recall_on_golden_set():
    with open(Path(__file__).parent / "schema_test_cases.json") as f:
        cases = json.load(f)
    pii_cases = [c for c in cases if c["expected"]["is_pii"]]
    detected = sum(1 for c in pii_cases
                   if detector.detect(c["input"])["is_pii"])
    recall = detected / len(pii_cases)
    assert recall >= 0.80, f"Recall {recall:.2f} below threshold"


def test_precision_on_golden_set():
    """Not in the task doc's given tests -- QUALITY_CRITERIA.md commits to
    precision >= 0.70 on the golden set, so it needs its own assertion,
    not just a number in eval_report.md nobody enforces.
    """
    with open(Path(__file__).parent / "schema_test_cases.json") as f:
        cases = json.load(f)
    predicted_positive = [c for c in cases if detector.detect(c["input"])["is_pii"]]
    if not predicted_positive:
        pytest.fail("Detector predicted zero PII columns -- cannot compute precision")
    correct = sum(1 for c in predicted_positive if c["expected"]["is_pii"])
    precision = correct / len(predicted_positive)
    assert precision >= 0.70, f"Precision {precision:.2f} below threshold"
