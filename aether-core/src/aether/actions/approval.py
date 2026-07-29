"""Durable trusted approval inbox for exact, expiring, single-use actions."""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, TYPE_CHECKING

from aether.contracts.actions import (
    ActionApproval,
    ActionProposal,
    ActionResult,
    ActionRisk,
    ActionScope,
    ActionTarget,
    canonical_action_hash,
    proposal_from_payload,
    proposal_payload,
    ApprovalOutcome,
    ApprovalStatus,
    PendingAction,
)
from aether.contracts.event_types import EventType
from aether.events import EventBus
from aether.utils.ids import new_id

if TYPE_CHECKING:
    from aether.actions.path import GovernedActionPath


class ApprovalError(RuntimeError):
    """Base approval lifecycle error."""


class ApprovalNotFound(ApprovalError):
    pass


class ApprovalExpired(ApprovalError):
    pass


class ApprovalStateError(ApprovalError):
    pass


class ApprovalIntegrityError(ApprovalError):
    pass


def _utc_now_dt() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)



def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "value"):
        return _json_safe(value.value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def result_payload(result: ActionResult) -> dict[str, Any]:
    return _json_safe(asdict(result))


def result_from_payload(payload: Mapping[str, Any]) -> ActionResult:
    return ActionResult(
        action_id=str(payload["action_id"]),
        ok=bool(payload["ok"]),
        status=str(payload["status"]),
        output=payload.get("output"),
        error=payload.get("error"),
        metadata=dict(payload.get("metadata") or {}),
        failure_fingerprint=payload.get("failure_fingerprint"),
    )


class PendingActionStore:
    """SQLite-backed pending-action store with immutable approval records."""

    def __init__(
        self,
        path: Path,
        *,
        clock: Callable[[], datetime] | None = None,
        default_ttl_seconds: int = 900,
    ) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock or _utc_now_dt
        self.default_ttl_seconds = max(1, int(default_ttl_seconds))
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS pending_actions (
                    approval_id TEXT PRIMARY KEY,
                    action_id TEXT NOT NULL UNIQUE,
                    action_hash TEXT NOT NULL UNIQUE,
                    proposal_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    requested_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    request_channel TEXT,
                    requested_by TEXT,
                    request_event_id TEXT,
                    decided_at TEXT,
                    decided_by TEXT,
                    decision_reason TEXT,
                    decision_channel TEXT,
                    consumed_at TEXT,
                    result_json TEXT,
                    continuation_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_pending_status_expiry
                    ON pending_actions(status, expires_at);
                CREATE TABLE IF NOT EXISTS approval_records (
                    record_id TEXT PRIMARY KEY,
                    approval_id TEXT NOT NULL,
                    action_hash TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    principal TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    decided_at TEXT NOT NULL,
                    FOREIGN KEY(approval_id) REFERENCES pending_actions(approval_id)
                );
                CREATE TRIGGER IF NOT EXISTS approval_records_immutable_update
                BEFORE UPDATE ON approval_records
                BEGIN
                    SELECT RAISE(ABORT, 'approval records are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS approval_records_immutable_delete
                BEFORE DELETE ON approval_records
                BEGIN
                    SELECT RAISE(ABORT, 'approval records are immutable');
                END;
                """
            )

    def create_or_get(
        self,
        proposal: ActionProposal,
        *,
        request_channel: str | None = None,
        requested_by: str | None = None,
        request_event_id: str | None = None,
        ttl_seconds: int | None = None,
    ) -> tuple[PendingAction, bool]:
        action_hash = canonical_action_hash(proposal)
        now = self.clock()
        requested_at = _iso(now)
        expires_at = _iso(now + timedelta(seconds=max(1, int(ttl_seconds or self.default_ttl_seconds))))
        approval_id = new_id("approval")
        proposal_json = json.dumps(proposal_payload(proposal), ensure_ascii=False, sort_keys=True)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM pending_actions WHERE action_id = ? OR action_hash = ?",
                (proposal.action_id, action_hash),
            ).fetchone()
            if existing is not None:
                connection.commit()
                return self._row_to_pending(existing), False
            connection.execute(
                """
                INSERT INTO pending_actions (
                    approval_id, action_id, action_hash, proposal_json, status,
                    requested_at, expires_at, request_channel, requested_by, request_event_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    approval_id,
                    proposal.action_id,
                    action_hash,
                    proposal_json,
                    ApprovalStatus.PENDING.value,
                    requested_at,
                    expires_at,
                    request_channel,
                    requested_by,
                    request_event_id,
                ),
            )
            row = connection.execute(
                "SELECT * FROM pending_actions WHERE approval_id = ?", (approval_id,)
            ).fetchone()
            connection.commit()
        assert row is not None
        return self._row_to_pending(row), True

    def save_continuation(self, approval_id: str, continuation: Mapping[str, Any]) -> PendingAction:
        payload = json.dumps(_json_safe(continuation), ensure_ascii=False, sort_keys=True)
        with self._lock, self._connect() as connection:
            updated = connection.execute(
                "UPDATE pending_actions SET continuation_json = ? WHERE approval_id = ?",
                (payload, approval_id),
            ).rowcount
            if not updated:
                raise ApprovalNotFound(approval_id)
            row = connection.execute(
                "SELECT * FROM pending_actions WHERE approval_id = ?", (approval_id,)
            ).fetchone()
        assert row is not None
        return self._row_to_pending(row)

    def get(self, approval_id: str) -> PendingAction:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM pending_actions WHERE approval_id = ?", (approval_id,)
            ).fetchone()
        if row is None:
            raise ApprovalNotFound(approval_id)
        return self._row_to_pending(row)

    def list(self, status: ApprovalStatus | str | None = None) -> list[PendingAction]:
        query = "SELECT * FROM pending_actions"
        params: tuple[Any, ...] = ()
        if status is not None:
            normalized = ApprovalStatus(str(status)).value
            query += " WHERE status = ?"
            params = (normalized,)
        query += " ORDER BY requested_at DESC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._row_to_pending(row) for row in rows]

    def expire_due(self) -> list[PendingAction]:
        now = _iso(self.clock())
        expired_ids: list[str] = []
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT approval_id FROM pending_actions WHERE status = ? AND expires_at <= ?",
                (ApprovalStatus.PENDING.value, now),
            ).fetchall()
            expired_ids = [str(row["approval_id"]) for row in rows]
            if expired_ids:
                placeholders = ",".join("?" for _ in expired_ids)
                connection.execute(
                    f"UPDATE pending_actions SET status = ? WHERE approval_id IN ({placeholders})",
                    (ApprovalStatus.EXPIRED.value, *expired_ids),
                )
            connection.commit()
        return [self.get(approval_id) for approval_id in expired_ids]

    def decide(
        self,
        approval_id: str,
        *,
        approved: bool,
        principal: str,
        reason: str,
        channel: str,
    ) -> PendingAction:
        if not principal.strip():
            raise ValueError("principal is required")
        if not reason.strip():
            raise ValueError("decision reason is required")
        if not channel.strip():
            raise ValueError("decision channel is required")
        now_dt = self.clock()
        now = _iso(now_dt)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM pending_actions WHERE approval_id = ?", (approval_id,)
            ).fetchone()
            if row is None:
                connection.rollback()
                raise ApprovalNotFound(approval_id)
            current = ApprovalStatus(str(row["status"]))
            if current == ApprovalStatus.PENDING and _parse_time(str(row["expires_at"])) <= now_dt:
                connection.execute(
                    "UPDATE pending_actions SET status = ? WHERE approval_id = ?",
                    (ApprovalStatus.EXPIRED.value, approval_id),
                )
                connection.commit()
                raise ApprovalExpired(approval_id)
            if current != ApprovalStatus.PENDING:
                connection.commit()
                return self.get(approval_id)

            decision = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
            connection.execute(
                """
                INSERT INTO approval_records (
                    record_id, approval_id, action_hash, decision, principal, reason, channel, decided_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("approval-record"),
                    approval_id,
                    str(row["action_hash"]),
                    decision.value,
                    principal,
                    reason,
                    channel,
                    now,
                ),
            )
            connection.execute(
                """
                UPDATE pending_actions
                SET status = ?, decided_at = ?, decided_by = ?, decision_reason = ?, decision_channel = ?
                WHERE approval_id = ?
                """,
                (decision.value, now, principal, reason, channel, approval_id),
            )
            connection.commit()
        return self.get(approval_id)

    def claim(self, approval_id: str) -> tuple[PendingAction, bool]:
        """Claim an approved action for one execution.

        Returns (record, replayed). A consumed record returns its cached result and
        never executes again. An in-flight execution raises instead of guessing.
        """
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM pending_actions WHERE approval_id = ?", (approval_id,)
            ).fetchone()
            if row is None:
                connection.rollback()
                raise ApprovalNotFound(approval_id)
            status = ApprovalStatus(str(row["status"]))
            if status == ApprovalStatus.CONSUMED:
                connection.commit()
                return self._row_to_pending(row), True
            if status == ApprovalStatus.EXECUTING:
                connection.commit()
                raise ApprovalStateError("Approval execution is already in progress")
            if status == ApprovalStatus.EXPIRED:
                connection.commit()
                raise ApprovalExpired(approval_id)
            if status != ApprovalStatus.APPROVED:
                connection.commit()
                raise ApprovalStateError(f"Approval is not executable from state: {status.value}")
            updated = connection.execute(
                "UPDATE pending_actions SET status = ? WHERE approval_id = ? AND status = ?",
                (ApprovalStatus.EXECUTING.value, approval_id, ApprovalStatus.APPROVED.value),
            ).rowcount
            if updated != 1:
                connection.rollback()
                raise ApprovalStateError("Approval claim lost a concurrent race")
            connection.commit()
        return self.get(approval_id), False

    def finalize(self, approval_id: str, result: ActionResult) -> PendingAction:
        now = _iso(self.clock())
        payload = json.dumps(result_payload(result), ensure_ascii=False, sort_keys=True)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            updated = connection.execute(
                """
                UPDATE pending_actions
                SET status = ?, consumed_at = ?, result_json = ?
                WHERE approval_id = ? AND status = ?
                """,
                (
                    ApprovalStatus.CONSUMED.value,
                    now,
                    payload,
                    approval_id,
                    ApprovalStatus.EXECUTING.value,
                ),
            ).rowcount
            if updated != 1:
                connection.rollback()
                raise ApprovalStateError("Approval was not in executing state during finalization")
            connection.commit()
        return self.get(approval_id)

    def approval_records(self, approval_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM approval_records WHERE approval_id = ? ORDER BY decided_at",
                (approval_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _row_to_pending(self, row: sqlite3.Row) -> PendingAction:
        proposal_data = json.loads(str(row["proposal_json"]))
        proposal = proposal_from_payload(proposal_data)
        expected_hash = canonical_action_hash(proposal)
        stored_hash = str(row["action_hash"])
        if expected_hash != stored_hash:
            raise ApprovalIntegrityError(
                f"Pending action hash mismatch for {row['approval_id']}: stored proposal was modified"
            )
        result = result_from_payload(json.loads(str(row["result_json"]))) if row["result_json"] else None
        continuation = json.loads(str(row["continuation_json"])) if row["continuation_json"] else None
        return PendingAction(
            approval_id=str(row["approval_id"]),
            action_id=str(row["action_id"]),
            action_hash=stored_hash,
            status=ApprovalStatus(str(row["status"])),
            proposal=proposal,
            requested_at=str(row["requested_at"]),
            expires_at=str(row["expires_at"]),
            request_channel=row["request_channel"],
            requested_by=row["requested_by"],
            decided_at=row["decided_at"],
            decided_by=row["decided_by"],
            decision_reason=row["decision_reason"],
            decision_channel=row["decision_channel"],
            consumed_at=row["consumed_at"],
            result=result,
            continuation=continuation,
        )


class TrustedApprovalInbox:
    """Authenticated decision and exact-once resumption service."""

    def __init__(
        self,
        store: PendingActionStore,
        action_path: "GovernedActionPath",
        event_bus: EventBus,
    ) -> None:
        self.store = store
        self.action_path = action_path
        self.event_bus = event_bus

    def sweep_expired(self) -> list[PendingAction]:
        records = self.store.expire_due()
        for pending in records:
            self.event_bus.emit(
                EventType.APPROVAL_EXPIRED,
                actor="aether.approval-inbox",
                payload={
                    "approval_id": pending.approval_id,
                    "action_id": pending.action_id,
                    "action_hash": pending.action_hash,
                    "expires_at": pending.expires_at,
                },
                severity="warning",
                correlation_id=pending.proposal.correlation_id,
            )
        return records

    def list(self, status: ApprovalStatus | str | None = ApprovalStatus.PENDING) -> list[PendingAction]:
        self.sweep_expired()
        return self.store.list(status)

    def get(self, approval_id: str) -> PendingAction:
        self.sweep_expired()
        return self.store.get(approval_id)

    async def decide_and_resume(
        self,
        approval_id: str,
        *,
        approved: bool,
        principal: str,
        reason: str,
        channel: str,
    ) -> ApprovalOutcome:
        try:
            pending = self.store.decide(
                approval_id,
                approved=approved,
                principal=principal,
                reason=reason,
                channel=channel,
            )
        except ApprovalExpired:
            expired = self.store.get(approval_id)
            self.event_bus.emit(
                EventType.APPROVAL_EXPIRED,
                actor="aether.approval-inbox",
                payload={"approval_id": approval_id, "action_id": expired.action_id},
                severity="warning",
                correlation_id=expired.proposal.correlation_id,
            )
            return ApprovalOutcome(expired)

        if not approved and pending.status in {
            ApprovalStatus.APPROVED, ApprovalStatus.EXECUTING, ApprovalStatus.CONSUMED
        }:
            self.event_bus.emit(
                EventType.APPROVAL_REPLAY_BLOCKED,
                actor="aether.approval-inbox",
                payload={
                    "approval_id": pending.approval_id,
                    "action_id": pending.action_id,
                    "principal": principal,
                    "requested_decision": "rejected",
                    "existing_status": pending.status.value,
                },
                severity="warning",
                correlation_id=pending.proposal.correlation_id,
            )
            return ApprovalOutcome(pending, pending.result, replayed=True)

        if pending.status == ApprovalStatus.REJECTED:
            self.event_bus.emit(
                EventType.APPROVAL_REJECTED,
                actor="aether.approval-inbox",
                payload={
                    "approval_id": pending.approval_id,
                    "action_id": pending.action_id,
                    "action_hash": pending.action_hash,
                    "principal": pending.decided_by,
                    "reason": pending.decision_reason,
                    "channel": pending.decision_channel,
                },
                severity="warning",
                correlation_id=pending.proposal.correlation_id,
            )
            return ApprovalOutcome(pending)

        if pending.status == ApprovalStatus.EXPIRED:
            return ApprovalOutcome(pending)

        if pending.status == ApprovalStatus.CONSUMED:
            self.event_bus.emit(
                EventType.APPROVAL_REPLAY_BLOCKED,
                actor="aether.approval-inbox",
                payload={
                    "approval_id": pending.approval_id,
                    "action_id": pending.action_id,
                    "principal": principal,
                    "cached_result": True,
                },
                severity="warning",
                correlation_id=pending.proposal.correlation_id,
            )
            return ApprovalOutcome(pending, pending.result, replayed=True)

        if pending.status != ApprovalStatus.APPROVED:
            raise ApprovalStateError(f"Approval cannot resume from state: {pending.status.value}")

        self.event_bus.emit(
            EventType.APPROVAL_APPROVED,
            actor="aether.approval-inbox",
            payload={
                "approval_id": pending.approval_id,
                "action_id": pending.action_id,
                "action_hash": pending.action_hash,
                "principal": pending.decided_by,
                "reason": pending.decision_reason,
                "channel": pending.decision_channel,
            },
            correlation_id=pending.proposal.correlation_id,
        )

        claimed, replayed = self.store.claim(approval_id)
        if replayed:
            return ApprovalOutcome(claimed, claimed.result, replayed=True)
        self.event_bus.emit(
            EventType.ACTION_RESUME_REQUESTED,
            actor="aether.approval-inbox",
            payload={
                "approval_id": claimed.approval_id,
                "action_id": claimed.action_id,
                "action_hash": claimed.action_hash,
                "principal": claimed.decided_by,
            },
            correlation_id=claimed.proposal.correlation_id,
        )
        trusted = ActionApproval(
            principal=str(claimed.decided_by),
            scopes=claimed.proposal.required_scopes,
            reason=str(claimed.decision_reason),
            approval_id=claimed.approval_id,
            action_hash=claimed.action_hash,
            issued_at=claimed.decided_at,
            expires_at=claimed.expires_at,
            channel=claimed.decision_channel,
        )
        result = await self.action_path.execute(claimed.proposal, trusted)
        finalized = self.store.finalize(approval_id, result)
        self.event_bus.emit(
            EventType.APPROVAL_CONSUMED,
            actor="aether.approval-inbox",
            payload={
                "approval_id": finalized.approval_id,
                "action_id": finalized.action_id,
                "action_hash": finalized.action_hash,
                "result_status": result.status,
                "result_ok": result.ok,
            },
            severity="info" if result.ok else "error",
            correlation_id=finalized.proposal.correlation_id,
        )
        return ApprovalOutcome(finalized, result)
