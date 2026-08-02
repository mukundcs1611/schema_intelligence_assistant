"""Thin wrappers around the already-tested Day 1 / Day 2 modules. No new
detection, generation, or retrieval logic lives here -- these three
functions are the agent's entire surface onto the rest of the system, and
each one just calls straight through to code that already has its own
recall/precision/Recall@3 guarantees. Duplicating any of that logic here
would risk silently diverging from numbers already earned.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "pii-detector"))
sys.path.insert(0, str(_ROOT / "masking-generator"))
sys.path.insert(0, str(_ROOT / "rag"))

from detector import PiiDetector  # noqa: E402
from generator import MaskingConfigGenerator  # noqa: E402
from retrieve import retrieve as _retrieve  # noqa: E402

_detector = PiiDetector()
_generator = MaskingConfigGenerator()


def detect_pii_columns(schema: list) -> list:
    """schema: list of column descriptor dicts. Returns list[DetectionResult]."""
    return _detector.detect_all(schema)


def generate_masking_config(detections: list) -> dict:
    """detections: list[DetectionResult]. Returns the masking job config dict."""
    return _generator.generate(detections)


def search_masking_docs(query: str, pii_category_filter: str = None) -> list:
    """Returns a list of chunk dicts (chunk_id, source_file, text, pii_category, ...)."""
    return _retrieve(query, pii_category_filter=pii_category_filter)
