"""Deterministic governance for provider-neutral action proposals."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from aether.contracts.actions import (
    ActionApproval, ActionDecision, ActionProposal, ActionRisk, ActionScope, canonical_action_hash,
)
from aether.governance.north_star_authority import NorthStarAuthority
from aether.governance.proposal import Proposal, ProposalType


_RISK_ORDER = {
    ActionRisk.LOW: 0,
    ActionRisk.MEDIUM: 1,
    ActionRisk.HIGH: 2,
    ActionRisk.CRITICAL: 3,
}


class ActionGovernor:
    def __init__(self, policy_path: Path | None = None, authority: NorthStarAuthority | None = None):
        self.policy_path = policy_path or Path(__file__).with_name("action_policy.yaml")
        self.policy = yaml.safe_load(self.policy_path.read_text(encoding="utf-8")) or {}
        self.authority = authority or NorthStarAuthority()

    def review(self, proposal: ActionProposal, approval: ActionApproval | None = None) -> ActionDecision:
        reasons: list[str] = []
        warnings: list[str] = []
        if not proposal.reason.strip():
            return ActionDecision(False, "denied", ("Action reason is required.",))
        if not proposal.operation.strip():
            return ActionDecision(False, "denied", ("Action operation is required.",))

        allowed = {ActionScope(item) for item in self.policy.get("allowed_scopes", [])}
        unknown = set(proposal.required_scopes) - allowed
        if unknown:
            return ActionDecision(False, "denied", (f"Unknown scopes: {sorted(map(str, unknown))}",))

        approval_principal = approval.principal.strip().casefold() if approval else ""
        founder_approved = approval_principal in {"dee", "founder", "founder dee"}
        north_star = self.authority.evaluate(Proposal(
            action=f"{proposal.target}:{proposal.operation}",
            reason=proposal.reason,
            confidence=0.5,
            risk_pct={ActionRisk.LOW: 1, ActionRisk.MEDIUM: 10, ActionRisk.HIGH: 40, ActionRisk.CRITICAL: 90}[proposal.risk],
            proposal_type=ProposalType.EXECUTE_TASK,
            metadata={
                "action_id": proposal.action_id,
                "irreversible": not proposal.reversible,
                "approval_path_available": True,
                "dee_approved": founder_approved,
            },
        ))
        warnings.extend(north_star.warnings)
        if not north_star.approved:
            return ActionDecision(False, "denied", (north_star.veto_reason or "Northstar veto",), tuple(warnings))

        for rule in self.policy.get("auto_approve", []):
            rule_scopes = {ActionScope(item) for item in rule.get("scopes", [])}
            max_risk = ActionRisk(rule.get("max_risk", "low"))
            if (
                str(proposal.target) == str(rule.get("target"))
                and proposal.operation == rule.get("operation")
                and set(proposal.required_scopes).issubset(rule_scopes)
                and _RISK_ORDER[proposal.risk] <= _RISK_ORDER[max_risk]
                and (not rule.get("reversible", False) or proposal.reversible)
            ):
                return ActionDecision(True, "auto-approved", tuple(reasons), tuple(warnings))

        required_scopes = set(proposal.required_scopes)
        approval_rules = self.policy.get("approval_required", {})
        approval_scopes = {ActionScope(item) for item in approval_rules.get("scopes", [])}
        needs_approval = bool(required_scopes & approval_scopes)
        needs_approval = needs_approval or proposal.risk.value in set(approval_rules.get("risks", []))
        needs_approval = needs_approval or (bool(approval_rules.get("irreversible", True)) and not proposal.reversible)

        # Default-deny also means non-auto-approved operations need explicit approval.
        needs_approval = needs_approval or self.policy.get("default") == "deny"
        if not needs_approval:
            return ActionDecision(True, "policy-approved", tuple(reasons), tuple(warnings))
        if approval is None:
            return ActionDecision(False, "approval-required", ("Trusted approval is required.",), tuple(warnings))
        if not approval.principal.strip():
            return ActionDecision(False, "denied", ("Approval principal is required.",), tuple(warnings))
        if not approval.reason.strip():
            return ActionDecision(False, "denied", ("Approval reason is required.",), tuple(warnings))
        if not approval.action_hash:
            return ActionDecision(False, "denied", ("Approval is not bound to an action hash.",), tuple(warnings))
        if approval.action_hash != canonical_action_hash(proposal):
            return ActionDecision(False, "denied", ("Approval action hash does not match the exact proposal.",), tuple(warnings))
        if approval.expires_at:
            expires = datetime.fromisoformat(approval.expires_at.replace("Z", "+00:00")).astimezone(timezone.utc)
            if expires <= datetime.now(timezone.utc):
                return ActionDecision(False, "denied", ("Approval has expired.",), tuple(warnings))
        missing = required_scopes - set(approval.scopes)
        if missing:
            return ActionDecision(False, "denied", (f"Approval missing scopes: {sorted(map(str, missing))}",), tuple(warnings))
        return ActionDecision(True, "human-approved", (f"Approved by {approval.principal}",), tuple(warnings))
