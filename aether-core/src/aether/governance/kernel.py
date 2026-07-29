"""
Governance Kernel
=================
The central authority layer for proposal review, decision ledgering, and constitution enforcement.
"""

from pathlib import Path
from typing import List, Optional

from aether.database.manager import get_db
from aether.governance.north_star_authority import NorthStarAuthority
from aether.governance.proposal import Proposal, ReviewResult


class DecisionLedger:
    """SQLite-backed decision ledger."""

    def __init__(self, db_name: str = "governance"):
        self.conn = get_db(db_name)
        self._init_db()

    def _init_db(self):
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS decision_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    approved INTEGER NOT NULL,
                    alignment_score REAL,
                    veto_reason TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

    def record(self, proposal: Proposal, result: ReviewResult):
        with self.conn:
            self.conn.execute("""
                INSERT INTO decision_ledger (action, reason, approved, alignment_score, veto_reason)
                VALUES (?, ?, ?, ?, ?)
            """, (proposal.action, proposal.reason, int(result.approved), result.alignment_score, result.veto_reason))


class GovernanceKernel:
    """Primary governance decision authority engine."""

    def __init__(self, ledger: DecisionLedger | None = None, authority: NorthStarAuthority | None = None):
        self.ledger = ledger or DecisionLedger()
        self.authority = authority or NorthStarAuthority()

    def review(self, proposal: Proposal) -> ReviewResult:
        """Review proposal against North Star Authority and record in decision ledger."""
        result = self.authority.evaluate(proposal)
        self.ledger.record(proposal, result)
        return result
