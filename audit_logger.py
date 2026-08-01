"""SQLite audit log -- one row per detector decision. This is what
README.md's design decision #4 already commits to ("every automated and
human decision is persisted") but detector.py wasn't actually doing until
now.

Schema is deliberately narrow: just enough to answer the metrics
CUSTOMER_VALUE.md and SCALABILITY.md promise --
  - auto-configuration rate  = COUNT(is_pii AND NOT review_required) / COUNT(*)
  - review queue acceptance  = COUNT(human_decision matches suggestion) / COUNT(human_decision IS NOT NULL)
  - a forensic trail for exactly the kind of confident-miss case that
    prompted this file to get built (see next_of_kin in eval_report.md).
"""
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "audit_log.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    table_name TEXT NOT NULL,
    column_name TEXT NOT NULL,
    is_pii INTEGER NOT NULL,
    pii_category TEXT,
    confidence REAL NOT NULL,
    recommended_masking_function TEXT,
    review_required INTEGER NOT NULL,
    reasoning TEXT,
    source TEXT NOT NULL,
    suggested_rule_keyword TEXT,
    human_decision TEXT,
    human_decided_at TEXT
);
"""


class AuditLogger:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = str(db_path or os.environ.get("AUDIT_DB_PATH", DEFAULT_DB_PATH))
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute(SCHEMA)
        self._conn.commit()

    def log_decision(
        self,
        table_name: str,
        column_name: str,
        is_pii: bool,
        pii_category: Optional[str],
        confidence: float,
        recommended_masking_function: Optional[str],
        review_required: bool,
        reasoning: str,
        source: str,
        suggested_rule_keyword: Optional[str] = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO decisions "
            "(timestamp, table_name, column_name, is_pii, pii_category, confidence, "
            " recommended_masking_function, review_required, reasoning, source, suggested_rule_keyword) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                table_name,
                column_name,
                int(is_pii),
                pii_category,
                confidence,
                recommended_masking_function,
                int(review_required),
                reasoning,
                source,
                suggested_rule_keyword,
            ),
        )
        self._conn.commit()

    def record_human_review(self, table_name: str, column_name: str, human_decision: str) -> None:
        """Updates the most recent decision row for (table, column) with the
        PS team's actual call. This is the source of truth for review-queue
        acceptance rate -- powers CUSTOMER_VALUE.md's 30-day pilot metric.
        """
        self._conn.execute(
            "UPDATE decisions SET human_decision = ?, human_decided_at = ? "
            "WHERE id = (SELECT id FROM decisions WHERE table_name = ? AND column_name = ? "
            "ORDER BY id DESC LIMIT 1)",
            (
                human_decision,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                table_name,
                column_name,
            ),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
