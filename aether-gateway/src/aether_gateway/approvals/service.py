"""Shared approval-inbox application service for every operator surface."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from aether.contracts import ApprovalStatus, PendingAction

from .coordinator import ApprovalCoordinator, ApprovalResumeOutcome


class ApprovalInboxService:
    """One application boundary for Telegram, HTTP/AionUi, and future surfaces.

    Authentication stays at each transport boundary. Once a trusted principal is
    established, every surface uses this service for listing, inspection, and
    exact-once decisions.
    """

    def __init__(self, coordinator: ApprovalCoordinator) -> None:
        self.coordinator = coordinator
        # Compatibility for existing adapter/test code while the transport
        # surfaces migrate from direct coordinator access.
        self.inbox = coordinator.inbox

    def sweep_expired(self) -> list[PendingAction]:
        return self.inbox.sweep_expired()

    def list(self, status: ApprovalStatus | str | None = ApprovalStatus.PENDING) -> list[PendingAction]:
        self.sweep_expired()
        return self.inbox.list(status)

    def get(self, approval_id: str) -> PendingAction:
        self.sweep_expired()
        return self.inbox.get(approval_id)

    def list_for_context(
        self,
        *,
        metadata_key: str,
        metadata_value: Any,
        status: ApprovalStatus | str | None = ApprovalStatus.PENDING,
    ) -> list[PendingAction]:
        rows: list[PendingAction] = []
        for pending in self.list(status):
            candidate = pending.proposal.metadata.get(metadata_key)
            if self._same_scalar(candidate, metadata_value):
                rows.append(pending)
        return rows

    async def decide(
        self,
        approval_id: str,
        *,
        approved: bool,
        principal: str,
        reason: str,
        channel: str,
        expected_action_hash: str | None = None,
    ) -> ApprovalResumeOutcome:
        pending = self.get(approval_id)
        if expected_action_hash is not None and pending.action_hash != expected_action_hash:
            raise ValueError("approval action hash does not match the operator view")
        return await self.coordinator.decide(
            approval_id,
            approved=approved,
            principal=principal,
            reason=reason,
            channel=channel,
        )

    def status_counts(self) -> dict[str, int]:
        self.sweep_expired()
        return {
            status.value: len(self.inbox.list(status))
            for status in ApprovalStatus
        }

    @staticmethod
    def _same_scalar(left: Any, right: Any) -> bool:
        if left is None or right is None:
            return left is right
        try:
            return int(left) == int(right)
        except (TypeError, ValueError):
            return str(left) == str(right)
