"""Gateway coordinator for trusted decisions and cognitive continuation."""
from __future__ import annotations

from dataclasses import dataclass

from aether.actions import TrustedApprovalInbox
from aether.cognition import AetherCognitiveGateway
from aether.contracts import ApprovalOutcome, Expression


@dataclass(frozen=True)
class ApprovalResumeOutcome:
    approval: ApprovalOutcome
    expression: Expression | None = None


class ApprovalCoordinator:
    def __init__(self, inbox: TrustedApprovalInbox, cognition: AetherCognitiveGateway) -> None:
        self.inbox = inbox
        self.cognition = cognition

    async def decide(
        self,
        approval_id: str,
        *,
        approved: bool,
        principal: str,
        reason: str,
        channel: str,
    ) -> ApprovalResumeOutcome:
        outcome = await self.inbox.decide_and_resume(
            approval_id,
            approved=approved,
            principal=principal,
            reason=reason,
            channel=channel,
        )
        expression = None
        if approved and outcome.result is not None and not outcome.replayed:
            expression = await self.cognition.resume_after_approval(outcome.pending, outcome.result)
        return ApprovalResumeOutcome(outcome, expression)
