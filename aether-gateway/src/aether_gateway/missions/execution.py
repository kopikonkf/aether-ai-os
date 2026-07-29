"""Gateway adapter connecting missions to the governed action and approval paths."""
from __future__ import annotations

from aether.actions import ApprovalNotFound, PendingActionStore
from aether.contracts import ActionProposal, ActionResult, ApprovalStatus, ResumableActionExecutor


class GovernedMissionActionAdapter:
    adapter_id = "aether.mission-action-adapter"

    def __init__(self, executor: ResumableActionExecutor, pending_store: PendingActionStore) -> None:
        self.executor = executor
        self.pending_store = pending_store

    async def execute(self, proposal: ActionProposal) -> ActionResult:
        return await self.executor.execute(proposal)

    async def approval_result(self, approval_id: str) -> ActionResult | None:
        try:
            pending = self.pending_store.get(approval_id)
        except ApprovalNotFound:
            return ActionResult(approval_id, False, "approval-not-found", error="approval checkpoint no longer exists")
        if pending.status in {ApprovalStatus.PENDING, ApprovalStatus.APPROVED, ApprovalStatus.EXECUTING}:
            return None
        if pending.status == ApprovalStatus.CONSUMED:
            return pending.result or ActionResult(pending.action_id, False, "consumed-without-result", error="approval consumed without cached result")
        return ActionResult(
            pending.action_id,
            False,
            pending.status.value,
            error=f"mission action approval ended in state {pending.status.value}",
            metadata={"approval_id": approval_id},
        )
