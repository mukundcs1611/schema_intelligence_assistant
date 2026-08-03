"""AI output quality test suite -- all 6 required test types.

Run from agent/:  pytest tests/quality_tests.py

(pytest.ini in agent/ adds quality_tests.py to the collected file patterns;
the task doc names this file, and its name doesn't match pytest's default
test_*.py glob.)

The types, in the order the task doc lists them:
  1. Semantic correctness  -- keyword assertion, not string matching
  2. Grounding enforcement -- tool call interception
  3. Out-of-scope rejection
  4. PII detection accuracy regression
  5. Masking config completeness
  6. A/B baseline          -- see ab_comparison.py, a script rather than a
                              test, since it establishes a baseline rather
                              than asserting a pass/fail condition

Why these assert on keywords and behaviour rather than exact strings: the
agent's prose comes from an LLM, so asserting on exact output would make
the suite fail on harmless rewording while still passing on answers that
are fluent but ungrounded. Each test below asserts the property that
actually matters -- that the answer contains the right concepts, that
retrieval genuinely ran, that no answer was invented -- not that the model
produced one specific sentence.
"""
import contextlib
import json
import sys
from pathlib import Path

import pytest

_AGENT_DIR = Path(__file__).resolve().parent.parent
_ROOT = _AGENT_DIR.parent
sys.path.insert(0, str(_AGENT_DIR))
sys.path.insert(0, str(_ROOT / "pii-detector"))
sys.path.insert(0, str(_ROOT / "masking-generator"))

import agent as agent_module  # noqa: E402
from agent import SchemaIntelligenceAgent  # noqa: E402
from detector import PiiDetector  # noqa: E402
from generator import MaskingConfigGenerator  # noqa: E402

agent = SchemaIntelligenceAgent()
detector = PiiDetector()
generator = MaskingConfigGenerator()

CORPUS_DIR = _ROOT / "rag" / "corpus"
GOLDEN_SET = _ROOT / "pii-detector" / "tests" / "schema_test_cases.json"

TRACKED_TOOLS = ("detect_pii_columns", "generate_masking_config", "search_masking_docs")


class _Tracker:
    def __init__(self):
        self.called_tools = []


@contextlib.contextmanager
def tool_call_tracker():
    """Intercepts the agent's tool calls by swapping the module-level names
    agent.py imported. Patching the names in agent's namespace (not tools')
    is what actually intercepts, since `from tools import x` binds x into
    agent at import time.
    """
    tracker = _Tracker()
    originals = {name: getattr(agent_module, name) for name in TRACKED_TOOLS}

    def wrap(name, original):
        def wrapped(*args, **kwargs):
            tracker.called_tools.append(name)
            return original(*args, **kwargs)
        return wrapped

    for name, original in originals.items():
        setattr(agent_module, name, wrap(name, original))
    try:
        yield tracker
    finally:
        for name, original in originals.items():
            setattr(agent_module, name, original)


def response_cites_source(response: str) -> bool:
    """True only if the response cites a document that actually exists in
    the corpus -- a citation naming a file we don't ship would be a
    fabricated citation, which is worse than no citation at all.
    """
    if "(Source:" not in response and "(Sources:" not in response:
        return False
    tail = response.rsplit("(", 1)[-1].rstrip(")\n ")
    cited = [c.strip() for c in tail.split(":", 1)[-1].split(",")]
    corpus_files = {f.name for f in CORPUS_DIR.glob("*.md")}
    return bool(cited) and all(c in corpus_files for c in cited)


def assert_no_hallucination(response: str, forbidden_answer: str) -> None:
    """The agent must not answer an out-of-scope question. If the actual
    answer to the question appears in the response, it answered it.
    """
    assert forbidden_answer.lower() not in response.lower(), (
        f"Response appears to answer an out-of-scope question (contains {forbidden_answer!r}): {response}"
    )


def load_test_schema(filename: str) -> list:
    with open(Path(__file__).resolve().parent / filename) as f:
        return json.load(f)


# -- 1. Semantic correctness ------------------------------------------------

def test_date_shift_answer_is_grounded():
    response = agent.chat("What does DATE_SHIFT do?")
    assert any(kw in response.lower()
               for kw in ["shift", "offset", "date", "preserve", "format"])
    assert response_cites_source(response)


def test_email_mask_answer_mentions_real_parameters():
    """Stronger than the keyword check above: these parameter names appear
    in email_mask.md and nowhere else, so a fluent-but-ungrounded answer
    would not contain them.
    """
    response = agent.chat("What parameters does EMAIL_MASK accept?")
    assert any(kw in response.lower() for kw in ["domain", "preserve_domain", "consistent_mapping"])
    assert response_cites_source(response)


# -- 2. Grounding enforcement (tool call interception) ----------------------

def test_doc_question_triggers_retrieval():
    with tool_call_tracker() as tracker:
        agent.chat("What parameters does EMAIL_MASK accept?")
    assert "search_masking_docs" in tracker.called_tools


def test_compliance_question_triggers_retrieval():
    with tool_call_tracker() as tracker:
        agent.chat("How do I comply with GDPR when masking customer data?")
    assert "search_masking_docs" in tracker.called_tools


def test_out_of_scope_question_calls_no_tools_at_all():
    """The inverse of the grounding rule: an out-of-scope question must not
    reach any tool, so nothing is retrieved and no answer text is generated
    from a tool result.
    """
    with tool_call_tracker() as tracker:
        agent.chat("What is the weather in Hyderabad?")
    assert tracker.called_tools == []


# -- 3. Out-of-scope rejection ---------------------------------------------

def test_out_of_scope_query_rejected():
    response = agent.chat("What is the capital of France?")
    assert_no_hallucination(response, "Paris")
    assert any(phrase in response.lower()
               for phrase in ["out of scope", "can't help", "masking", "data"])


def test_missing_schema_asks_rather_than_inventing():
    """Task doc interaction 7. The failure mode this guards against is the
    agent fabricating a schema to analyse -- observed directly during
    development, where the model invented five plausible ORDERS columns
    when asked about a single named column with no data attached.
    """
    fresh_agent = SchemaIntelligenceAgent()
    response = fresh_agent.chat("Mask this column: [no schema provided]")
    assert any(phrase in response.lower()
               for phrase in ["provide", "don't have a schema", "column descriptors"])
    # a fabricated schema would show up as invented column names
    for invented in ["order_id", "customer_id", "total_amount"]:
        assert invented not in response.lower()


# -- 4. PII detection accuracy regression ----------------------------------

def test_pii_detector_recall_regression():
    with open(GOLDEN_SET) as f:
        cases = json.load(f)
    pii_cases = [c for c in cases if c["expected"]["is_pii"]]
    detected = sum(1 for c in pii_cases if detector.detect(c["input"])["is_pii"])
    recall = detected / len(pii_cases)
    # 0.90, matching QUALITY_CRITERIA.md's stated target -- the task doc's
    # own template asserts 0.80, which is weaker than what we committed to.
    assert recall >= 0.90, f"PII recall regression: {recall:.2f} < 0.90"


def test_pii_detector_precision_regression():
    with open(GOLDEN_SET) as f:
        cases = json.load(f)
    predicted_positive = [c for c in cases if detector.detect(c["input"])["is_pii"]]
    assert predicted_positive, "detector predicted zero PII columns"
    correct = sum(1 for c in predicted_positive if c["expected"]["is_pii"])
    precision = correct / len(predicted_positive)
    assert precision >= 0.70, f"PII precision regression: {precision:.2f} < 0.70"


# -- 5. Masking config completeness ----------------------------------------

def test_masking_config_covers_high_confidence_detections():
    schema = load_test_schema("10_column_schema.json")
    detections = detector.detect_all(schema)
    config = generator.generate(detections)
    high_conf = [d for d in detections if d.confidence >= 0.80 and d.is_pii]
    configured = {r["column"] for r in config["masking_rules"]}
    for d in high_conf:
        assert d.column in configured, (
            f"{d.table}.{d.column} detected as PII at {d.confidence:.2f} but missing from masking_rules"
        )


def test_no_detection_is_silently_dropped():
    """Every column must land in exactly one bucket. A column that is
    neither configured, queued for review, nor counted as not-PII has been
    silently lost -- the failure mode the review queue exists to prevent.
    """
    schema = load_test_schema("10_column_schema.json")
    detections = detector.detect_all(schema)
    config = generator.generate(detections)
    assert sum(config["confidence_summary"].values()) == len(schema)
    configured = {r["column"] for r in config["masking_rules"]}
    queued = {r["column"] for r in config["review_queue"]}
    assert configured.isdisjoint(queued)


def test_every_masking_rule_cites_a_real_document():
    schema = load_test_schema("10_column_schema.json")
    config = generator.generate(detector.detect_all(schema))
    corpus_files = {f.name for f in CORPUS_DIR.glob("*.md")}
    for rule in config["masking_rules"]:
        assert rule["documentation_reference"] is not None
        assert rule["documentation_reference"].split("#")[0] in corpus_files
