"""Reviewer CLI: turns LLM-suggested keywords sitting in audit_log.db into
approved entries in promoted_rules.yaml. Never automatic -- see
promoted_rules.yaml's header and pii_patterns.py's get_promoted_keywords()
for the read side of this loop.

Run from pii-detector/: python promote_rules.py
"""
import argparse
import sqlite3
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from audit_logger import DEFAULT_DB_PATH  # noqa: E402

from pii_patterns import POSITIVE_NAME_KEYWORDS, PROMOTED_RULES_PATH  # noqa: E402

HEADER = (
    "# category -> list of approved keywords\n"
    "# Populated by promote_rules.py after a human reviewer approves an\n"
    "# LLM-suggested keyword. Merged on top of POSITIVE_NAME_KEYWORDS in\n"
    "# pii_patterns.py at read time -- the base dictionary is never modified\n"
    "# by this file.\n"
)


def load_promoted(yaml_path: Path) -> dict:
    if not yaml_path.exists():
        return {}
    with open(yaml_path) as f:
        return yaml.safe_load(f) or {}


def write_promoted(yaml_path: Path, data: dict) -> None:
    body = yaml.safe_dump(data, sort_keys=True, default_flow_style=False) if data else ""
    yaml_path.write_text(HEADER + "\n" + body)


def pending_suggestions(db_path: Path, promoted: dict, min_occurrences: int = 1) -> list[dict]:
    """Groups suggested_rule_keyword by (category, keyword), counting
    distinct columns that triggered each one. Already-promoted pairs are
    dropped -- promoted_rules.yaml is the single source of truth for
    "already handled", no separate DB flag to keep in sync.
    """
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT pii_category, suggested_rule_keyword,
                   COUNT(DISTINCT table_name || '.' || column_name) AS n,
                   GROUP_CONCAT(DISTINCT table_name || '.' || column_name) AS examples
            FROM decisions
            WHERE suggested_rule_keyword IS NOT NULL
            GROUP BY pii_category, suggested_rule_keyword
            HAVING n >= ?
            ORDER BY n DESC
            """,
            (min_occurrences,),
        ).fetchall()
    finally:
        conn.close()

    candidates = []
    for category, keyword, count, examples in rows:
        # Already promoted, or already in the hand-written base dictionary.
        # The base check matters: the model sometimes suggests the category's
        # own generic term (it proposed "email" off column "fld_23"), which
        # is already a rule and would be pure noise in the review queue.
        if keyword in promoted.get(category, []):
            continue
        if keyword in POSITIVE_NAME_KEYWORDS.get(category, []):
            continue
        candidates.append({
            "category": category,
            "keyword": keyword,
            "count": count,
            "examples": examples.split(",")[:3],
        })
    return candidates


def review_loop(candidates: list[dict], promoted: dict, yaml_path: Path) -> int:
    if not candidates:
        print("No pending suggestions.")
        return 0

    approved = 0
    for c in candidates:
        print(f"\n{c['category']} <- \"{c['keyword']}\"  (seen on {c['count']} distinct column(s))")
        print(f"  examples: {', '.join(c['examples'])}")
        answer = input("  approve? [y/N/q]: ").strip().lower()
        if answer == "q":
            break
        if answer == "y":
            promoted.setdefault(c["category"], [])
            if c["keyword"] not in promoted[c["category"]]:
                promoted[c["category"]].append(c["keyword"])
            write_promoted(yaml_path, promoted)
            approved += 1
            print(f"  promoted -- picked up by the next detect() call.")
        else:
            print("  skipped -- stays in the audit log, will resurface next run.")
    return approved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--yaml-path", type=Path, default=PROMOTED_RULES_PATH)
    parser.add_argument("--min-occurrences", type=int, default=1,
                         help="Only show suggestions seen on at least this many distinct columns.")
    args = parser.parse_args()

    if not args.db_path.exists():
        print(f"No audit log at {args.db_path} -- nothing to review.")
        return

    promoted = load_promoted(args.yaml_path)
    candidates = pending_suggestions(args.db_path, promoted, args.min_occurrences)
    approved = review_loop(candidates, promoted, args.yaml_path)
    print(f"\n{approved} keyword(s) promoted this run.")


if __name__ == "__main__":
    main()
