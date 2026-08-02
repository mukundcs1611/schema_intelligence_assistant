"""Day 2C tests. First two are verbatim from the task doc; sample_detections()
is our own fixture since the task doc references it without defining it.

Run from masking-generator/: pytest tests/
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from generator import MaskingConfigGenerator

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "pii-detector"))
from detector import DetectionResult  # noqa: E402

generator = MaskingConfigGenerator()


def sample_detections():
    return [
        DetectionResult(table="CUSTOMERS", column="email", is_pii=True, confidence=0.95,
                         pii_category="EMAIL", recommended_masking_function="EMAIL_MASK",
                         review_required=False, reasoning="matches EMAIL pattern"),
        DetectionResult(table="ORDERS", column="ref_code", is_pii=True, confidence=0.62,
                         pii_category="ACCOUNT_NUMBER", recommended_masking_function="ACCOUNT_MASK",
                         review_required=True, reasoning="column name ambiguous"),
        DetectionResult(table="ORDERS", column="quantity", is_pii=False, confidence=0.95,
                         pii_category=None, recommended_masking_function=None,
                         review_required=False, reasoning="generic operational field"),
    ]


def test_low_confidence_goes_to_review_queue():
    detections = [DetectionResult(column="ref_code", table="ORDERS",
                                   is_pii=True, confidence=0.62,
                                   pii_category="ACCOUNT_NUMBER",
                                   recommended_masking_function="ACCOUNT_MASK",
                                   review_required=True)]
    config = generator.generate(detections)
    assert any(r["column"] == "ref_code" for r in config["review_queue"])
    assert not any(r["column"] == "ref_code" for r in config["masking_rules"])


def test_documentation_references_exist():
    config = generator.generate(sample_detections())
    corpus_dir = Path(__file__).resolve().parent.parent.parent / "rag" / "corpus"
    corpus_files = {f.name for f in corpus_dir.glob("*.md")}
    for rule in config["masking_rules"]:
        doc_file = rule["documentation_reference"].split("#")[0]
        assert doc_file in corpus_files


def test_confidence_summary_counts_match():
    config = generator.generate(sample_detections())
    assert config["confidence_summary"] == {
        "auto_configured": 1, "requires_review": 1, "not_pii": 1,
    }


def test_uncertain_not_pii_goes_to_review_without_a_suggested_function():
    """Not in the task doc's given tests -- detector.py's own extension
    (blend case 3d, an ungrounded low-confidence "not PII" call) has to
    land somewhere in the generated config, or the safety net it exists
    for gets silently dropped between detection and the deliverable.
    """
    detections = [DetectionResult(table="LOGS", column="obscure_field", is_pii=False,
                                   confidence=0.45, pii_category=None,
                                   recommended_masking_function=None, review_required=True,
                                   reasoning="LLM says not-PII but with no rule-layer opinion to cross-check it")]
    config = generator.generate(detections)
    entry = next(r for r in config["review_queue"] if r["column"] == "obscure_field")
    assert entry["suggested_function"] is None
    assert entry["alternatives"] == []
    assert not any(r["column"] == "obscure_field" for r in config["masking_rules"])


def test_conflict_alternative_category_becomes_an_alternative():
    detections = [DetectionResult(table="ORDERS", column="acct_ref", is_pii=True,
                                   confidence=0.70, pii_category="SSN",
                                   recommended_masking_function="SSN_MASK",
                                   review_required=True, reasoning="conflicting signals",
                                   alternative_category="ACCOUNT_NUMBER")]
    config = generator.generate(detections)
    entry = next(r for r in config["review_queue"] if r["column"] == "acct_ref")
    assert entry["alternatives"] == ["ACCOUNT_MASK"]
