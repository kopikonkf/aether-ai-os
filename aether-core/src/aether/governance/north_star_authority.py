"""
North Star Authority
====================
Scored authority layer for North Star alignment.
Reads from DNA layer (north_star.yaml) and produces numeric alignment scores.
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

from aether.dna.loader import DNALoader
from aether.governance.proposal import Proposal, ReviewResult

logger = logging.getLogger(__name__)

VETO_THRESHOLD = 0.3

_IRREVERSIBLE_KEYWORDS = [
    "delete", "drop", "remove", "wipe", "reset",
    "deploy_live", "override_dee", "bypass_governance",
    "disable_constitution", "remove_rule",
]

_SKIP_REVIEW_KEYWORDS = [
    "skip_review", "force_deploy", "bypass_review",
    "no_backtest", "skip_backtest", "force_live",
]

_MILESTONE_CONFUSION_KEYWORDS = [
    "north_star_is_1000", "north_star_is_money", "redefine_north_star",
    "change_north_star",
]


class NorthStarAuthority:
    """Evaluates proposals against North Star sacred principles and milestones."""

    def __init__(self, dna_loader: DNALoader | None = None):
        self.dna_loader = dna_loader or DNALoader()
        self.north_star_data = self.dna_loader.load_north_star()

    def evaluate(self, proposal: Proposal) -> ReviewResult:
        """Evaluate a proposal against North Star principles."""
        action_lower = proposal.action.lower()
        reason_lower = proposal.reason.lower()
        full_text = f"{action_lower} {reason_lower}"
        
        score = 1.0
        warnings: List[str] = []
        
        # Check empty reason (SC4)
        if not proposal.reason.strip():
            score -= 0.3
            warnings.append("SC4 Violation: Proposal has no audit trail / empty reason.")

        # Check irreversible keywords without approval (SC3)
        for kw in _IRREVERSIBLE_KEYWORDS:
            if kw in full_text and not proposal.metadata.get("dee_approved", False):
                score -= 0.4
                warnings.append(f"SC3 Violation: Irreversible action '{kw}' requires explicit Dee approval.")
                break

        # Check review bypass (SC2)
        for kw in _SKIP_REVIEW_KEYWORDS:
            if kw in full_text:
                score -= 0.3
                warnings.append(f"SC2 Violation: Attempting to bypass review via '{kw}'.")
                break

        # Check milestone confusion (SC1/SC5)
        for kw in _MILESTONE_CONFUSION_KEYWORDS:
            if kw in full_text:
                score -= 0.5
                warnings.append(f"SC1/SC5 Violation: Milestone confusion detected via '{kw}'.")
                break

        score = max(0.0, min(1.0, score))
        approved = score >= VETO_THRESHOLD
        veto_reason = f"North Star Alignment score {score:.2f} is below veto threshold {VETO_THRESHOLD}" if not approved else None

        return ReviewResult(
            approved=approved,
            alignment_score=score,
            compounding_score=1.0,
            veto_reason=veto_reason,
            warnings=warnings,
        )
