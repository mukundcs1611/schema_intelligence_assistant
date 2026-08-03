"""Day 1B tests. First four are verbatim from the task doc; test 5 is our own
addition because QUALITY_CRITERIA.md commits to a precision target the doc's
own test set doesn't check.

Run from pii-detector/: pytest tests/
"""
import json
from pathlib import Path

import pytest
import pii_patterns
from detector import PiiDetector
from llm_cache import LlmCache
from audit_logger import AuditLogger

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
    # QUALITY_CRITERIA.md targets >= 0.90 (the JD's own template test only
    # asserted >= 0.80) -- raised to actually gate on our stated target.
    assert recall >= 0.90, f"Recall {recall:.2f} below threshold"


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


def test_promoted_keyword_extends_match(tmp_path, monkeypatch):
    """A keyword with no base-dictionary entry doesn't match until it's
    promoted -- then it does, on the very next call, no reload needed.
    """
    yaml_path = tmp_path / "promoted_rules.yaml"
    yaml_path.write_text("ACCOUNT_NUMBER:\n  - routing_num\n")

    assert pii_patterns.name_matches("routing_num", "ACCOUNT_NUMBER") is False

    monkeypatch.setattr(pii_patterns, "PROMOTED_RULES_PATH", yaml_path)
    monkeypatch.setattr(pii_patterns, "_promoted_cache", {"mtime": None, "data": {}})

    assert pii_patterns.name_matches("routing_num", "ACCOUNT_NUMBER") is True


def test_empty_overlay_is_a_no_op(tmp_path, monkeypatch):
    """A missing or empty promoted_rules.yaml must not change base-dict
    behavior -- regression guard, since this file ships empty by default.
    """
    missing_path = tmp_path / "does_not_exist.yaml"
    monkeypatch.setattr(pii_patterns, "PROMOTED_RULES_PATH", missing_path)
    monkeypatch.setattr(pii_patterns, "_promoted_cache", {"mtime": None, "data": {}})

    assert pii_patterns.get_promoted_keywords() == {}
    # a known base-dict keyword still matches with no overlay present
    assert pii_patterns.name_matches("email_address", "EMAIL") is True


def test_auto_configuration_rate_on_golden_set():
    """QUALITY_CRITERIA.md lists auto-configuration rate >= 0.80 as a Day 1
    success metric, but nothing asserted it -- so when one true positive
    started landing in review, eval_report.md kept claiming 1.00 until it
    was hand-checked. An unasserted target is a target that drifts.
    """
    with open(Path(__file__).parent / "schema_test_cases.json") as f:
        cases = json.load(f)
    true_positives = [
        r for r in (detector.detect(c["input"]) for c in cases if c["expected"]["is_pii"])
        if r["is_pii"]
    ]
    assert true_positives, "detector found no PII in the golden set"
    auto = sum(1 for r in true_positives if not r["review_required"])
    rate = auto / len(true_positives)
    assert rate >= 0.80, f"Auto-configuration rate {rate:.2f} below 0.80"


def test_no_pii_detection_above_threshold_is_left_in_review():
    """QUALITY_CRITERIA.md's "every PII detection below 0.80 in review queue
    (zero exceptions)" -- asserted in both directions, since the inverse
    (a high-confidence detection needlessly queued) would quietly erode the
    time saving the tool exists for.
    """
    with open(Path(__file__).parent / "schema_test_cases.json") as f:
        cases = json.load(f)
    for c in cases:
        r = detector.detect(c["input"])
        if not r["is_pii"]:
            continue
        if r["confidence"] < 0.80:
            assert r["review_required"], f"{c['input']['column_name']} below threshold but not queued"
        else:
            assert not r["review_required"], f"{c['input']['column_name']} above threshold but queued anyway"


class _CountingFakeClient:
    """Stands in for ollama.Client -- returns a fixed valid response and
    counts how many times .chat() was actually invoked, so the cache test
    below can assert the second identical call never reaches this client.
    """
    def __init__(self):
        self.calls = 0

    def chat(self, **kwargs):
        self.calls += 1
        return {"message": {"content": json.dumps({
            "is_pii": True, "pii_category": "EMAIL", "confidence": 0.9,
            "reasoning": "fake response for cache test", "suggested_rule_keyword": None,
        })}}


def test_identical_llm_call_is_served_from_cache(tmp_path):
    """Tier 1 caching: _llm_classify is temperature=0 (meant to be
    deterministic per input), so a repeated identical column must not
    re-invoke the client -- pure cost/latency win, not a behavior change.
    """
    fake_client = _CountingFakeClient()
    cache = LlmCache(db_path=tmp_path / "test_llm_cache.db")
    audit = AuditLogger(db_path=tmp_path / "test_audit.db")
    d = PiiDetector(client=fake_client, llm_cache=cache, audit_logger=audit)
    col = {"table_name": "CONTACTS", "column_name": "elektropost", "data_type": "VARCHAR(120)",
           "sample_values": ["someone at example dot com"], "nullable": True}

    r1 = d.detect(col)
    assert fake_client.calls == 1

    r2 = d.detect(col)
    assert fake_client.calls == 1, "second identical call must be served from cache, not the client"
    assert r1 == r2
