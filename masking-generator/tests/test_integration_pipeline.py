"""Integration test: Day 1 detector output feeds directly into the Day 2C
generator with no adaptation in between -- this is the seam the "3-4 days
of manual review -> automated" pitch actually depends on holding together.

Run from masking-generator/: pytest tests/
Requires Ollama running (qwen2.5:7b), same as pii-detector's own tests.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from generator import MaskingConfigGenerator

PII_DETECTOR_DIR = Path(__file__).resolve().parent.parent.parent / "pii-detector"
sys.path.insert(0, str(PII_DETECTOR_DIR))
from detector import PiiDetector  # noqa: E402


def test_detector_output_feeds_generator_directly():
    with open(PII_DETECTOR_DIR / "tests" / "schema_test_cases.json") as f:
        cases = json.load(f)
    schema = [c["input"] for c in cases[:10]]

    detections = PiiDetector().detect_all(schema)
    config = MaskingConfigGenerator().generate(detections)

    total = sum(config["confidence_summary"].values())
    assert total == len(schema), "every detection must land in exactly one confidence_summary bucket"

    rule_columns = {r["column"] for r in config["masking_rules"]}
    review_columns = {r["column"] for r in config["review_queue"]}
    assert rule_columns.isdisjoint(review_columns), "a column must never appear in both masking_rules and review_queue"

    for rule in config["masking_rules"]:
        assert rule["documentation_reference"] is not None
        # mirrors detector.py's own AUTO_CONFIGURE_THRESHOLD as a cross-module contract check
        assert rule["confidence"] >= 0.80
