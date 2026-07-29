"""
North Star Authority
====================
Deterministic authority layer for North Star alignment and hard governance vetoes.
Reads the canonical DNA North Star and never treats a numeric score as permission
to bypass Founder approval or constitutional amendment rules.
"""

from __future__ import annotations

import logging
from typing import List

from aether.dna.loader import DNALoader
from aether.governance.proposal import Proposal, ReviewResult

logger = logging.getLogger(__name__)

VETO_THRESHOLD = 0.3

_DESTRUCTIVE_KEYWORDS = [
    "drop database",
    "delete production",
    "wipe",
    "reset production",
    "deploy_live",
    "override_dee",
    "bypass_governance",
    "disable_constitution",
    "remove_rule",
]

_SKIP_REVIEW_KEYWORDS = [
    "skip_review",
    "force_deploy",
    "bypass_review",
    "no_backtest",
    "skip_backtest",
    "force_live",
]

_NORTH_STAR_AMENDMENT_KEYWORDS = [
    "north_star_is_1000",
    "north_star_is_money",
    "redefine_north_star",
    "change_north_star",
    "amend_north_star",
]


def _first_match(text: str, candidates: list[str]) -> str | None:
    return next((item for item in candidates if item in text), None)


class NorthStarAuthority:
    """Evaluate proposals against North Star principles and hard authority gates."""

    def __init__(self, dna_loader: DNALoader | None = None):
        self.dna_loader = dna_loader or DNALoader()
        if not self.dna_loader.verify_integrity():
            report = self.dna_loader.integrity_report()
            raise RuntimeError(
                "Aether DNA integrity verification failed: "
                + "; ".join(report.get("errors", []))
            )
        self.north_star_data = self.dna_loader.load_north_star()

    def evaluate(self, proposal: Proposal) -> ReviewResult:
        """Evaluate a proposal without allowing scoring to override hard vetoes."""
        action_lower = proposal.action.casefold()
        reason_lower = proposal.reason.casefold()
        full_text = f"{action_lower} {reason_lower}"

        score = 1.0
        warnings: List[str] = []
        hard_vetoes: List[str] = []

        metadata = proposal.metadata
        dee_approved = metadata.get("dee_approved") is True
        approval_path_available = metadata.get("approval_path_available") is True
        constitutional_amendment = metadata.get("constitutional_amendment") is True

        if not proposal.reason.strip():
            score -= 0.3
            warnings.append(
                "SC4 Violation: Proposal has no audit trail / empty reason."
            )

        skip_review = _first_match(full_text, _SKIP_REVIEW_KEYWORDS)
        if skip_review:
            hard_vetoes.append(
                f"SC2 hard veto: review bypass attempted via '{skip_review}'."
            )

        amendment = _first_match(full_text, _NORTH_STAR_AMENDMENT_KEYWORDS)
        if amendment and not (dee_approved and constitutional_amendment):
            hard_vetoes.append(
                "SC1/SC5 hard veto: North Star amendment requires explicit Dee "
                "approval and constitutional_amendment=true."
            )
        elif amendment:
            warnings.append(
                "Founder-authorized North Star amendment candidate; the full "
                "constitutional amendment protocol and reviewed source change remain required."
            )

        destructive = _first_match(full_text, _DESTRUCTIVE_KEYWORDS)
        irreversible = metadata.get("irreversible") is True or destructive is not None
        if irreversible and not dee_approved:
            if approval_path_available:
                score -= 0.4
                warnings.append(
                    "SC3: irreversible action requires exact Founder approval before execution."
                )
            else:
                hard_vetoes.append(
                    "SC3 hard veto: irreversible action has no explicit Dee approval "
                    "and no governed approval path."
                )
        elif irreversible:
            warnings.append(
                "SC3: irreversible action carries explicit Founder approval; backup, "
                "rollback, and exact action binding still apply."
            )

        score = max(0.0, min(1.0, score))
        if hard_vetoes:
            score = 0.0

        approved = not hard_vetoes and score >= VETO_THRESHOLD
        if hard_vetoes:
            veto_reason = " ".join(hard_vetoes)
        elif not approved:
            veto_reason = (
                f"North Star alignment score {score:.2f} is below veto threshold "
                f"{VETO_THRESHOLD}"
            )
        else:
            veto_reason = None

        return ReviewResult(
            approved=approved,
            alignment_score=score,
            compounding_score=1.0,
            veto_reason=veto_reason,
            warnings=warnings,
        )
