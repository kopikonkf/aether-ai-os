"""Safe approval-inbox presentation helpers."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from aether.contracts import PendingAction


def pending_to_dict(pending: PendingAction, *, include_result: bool = True) -> dict[str, Any]:
    proposal = pending.proposal
    payload: dict[str, Any] = {
        "approval_id": pending.approval_id,
        "action_id": pending.action_id,
        "action_hash": pending.action_hash,
        "status": pending.status.value,
        "requested_at": pending.requested_at,
        "expires_at": pending.expires_at,
        "request_channel": pending.request_channel,
        "requested_by": pending.requested_by,
        "decided_at": pending.decided_at,
        "decided_by": pending.decided_by,
        "decision_reason": pending.decision_reason,
        "decision_channel": pending.decision_channel,
        "consumed_at": pending.consumed_at,
        "proposal": {
            "target": proposal.target.value,
            "operation": proposal.operation,
            "reason": proposal.reason,
            "risk": proposal.risk.value,
            "reversible": proposal.reversible,
            "required_scopes": [scope.value for scope in proposal.required_scopes],
            "arguments": dict(proposal.arguments),
            "metadata": dict(proposal.metadata),
        },
    }
    if include_result and pending.result is not None:
        payload["result"] = asdict(pending.result)
    return payload


def format_pending(pending: PendingAction) -> str:
    scopes = ", ".join(scope.value for scope in pending.proposal.required_scopes) or "none"
    return (
        f"{pending.approval_id}\n"
        f"  {pending.proposal.target.value}/{pending.proposal.operation} | risk={pending.proposal.risk.value}\n"
        f"  scopes={scopes} | reversible={pending.proposal.reversible}\n"
        f"  reason={pending.proposal.reason}\n"
        f"  hash={pending.action_hash[:16]}… | expires={pending.expires_at}"
    )


def approval_card_text(pending: PendingAction) -> str:
    """Compact Founder-facing approval card without leaking full arguments."""
    proposal = pending.proposal
    arguments = dict(proposal.arguments)
    target = arguments.get("path") or arguments.get("target") or arguments.get("url")
    lines = [
        f"{proposal.target.value}/{proposal.operation}",
        f"Risk: {proposal.risk.value} · Reversible: {'yes' if proposal.reversible else 'no'}",
    ]
    if target:
        rendered = str(target)
        if len(rendered) > 180:
            rendered = rendered[:177] + "…"
        lines.append(f"Target: {rendered}")
    if proposal.reason:
        reason = proposal.reason.strip()
        if len(reason) > 220:
            reason = reason[:217] + "…"
        lines.append(f"Reason: {reason}")
    lines.append(f"Expires: {pending.expires_at}")
    lines.append("Choose once:")
    return "\n".join(lines)
