"""Durable append-only store for opportunities, mission plans, execution, and value evidence."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from aether.contracts.missions import (
    ExpectedValueBrief,
    MissionDecision,
    MissionDecisionType,
    MissionNotFound,
    MissionOutcome,
    MissionOutcomeState,
    MissionPlan,
    MissionStatus,
    MissionStepAttempt,
    MissionStepStatus,
    MissionTransition,
    MissionValueEvidence,
    MissionValueKind,
    mission_plan_from_payload,
    mission_plan_payload,
    opportunity_brief_from_payload,
    opportunity_brief_payload,
)
from aether.utils.ids import new_id
from aether.utils.time import utc_now


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _load(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    return json.loads(value)


class SQLiteMissionStore:
    store_id = "aether.missions.sqlite"

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS opportunity_briefs (
                    brief_id TEXT PRIMARY KEY,
                    brief_hash TEXT NOT NULL UNIQUE,
                    lane TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mission_plans (
                    mission_id TEXT PRIMARY KEY,
                    brief_id TEXT NOT NULL,
                    plan_hash TEXT NOT NULL UNIQUE,
                    lane TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(brief_id) REFERENCES opportunity_briefs(brief_id)
                );
                CREATE TABLE IF NOT EXISTS mission_decisions (
                    decision_id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL UNIQUE,
                    decision TEXT NOT NULL,
                    principal TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    decided_at TEXT NOT NULL,
                    FOREIGN KEY(mission_id) REFERENCES mission_plans(mission_id)
                );
                CREATE TABLE IF NOT EXISTS mission_transitions (
                    transition_id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL,
                    from_status TEXT,
                    to_status TEXT NOT NULL,
                    principal TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(mission_id) REFERENCES mission_plans(mission_id)
                );
                CREATE INDEX IF NOT EXISTS idx_mission_transitions
                    ON mission_transitions(mission_id, created_at);
                CREATE TABLE IF NOT EXISTS mission_step_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL,
                    step_id TEXT NOT NULL,
                    attempt_number INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    action_id TEXT NOT NULL,
                    approval_id TEXT,
                    output_json TEXT,
                    error TEXT,
                    failure_fingerprint TEXT,
                    estimated_cost_usd REAL NOT NULL,
                    metadata_json TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    FOREIGN KEY(mission_id) REFERENCES mission_plans(mission_id)
                );
                CREATE INDEX IF NOT EXISTS idx_mission_step_attempts
                    ON mission_step_attempts(mission_id, step_id, started_at);
                CREATE TABLE IF NOT EXISTS mission_value_evidence (
                    evidence_id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    description TEXT NOT NULL,
                    source TEXT NOT NULL,
                    amount_usd REAL,
                    external_reference TEXT,
                    related_evidence_id TEXT,
                    verified_by TEXT,
                    metadata_json TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    FOREIGN KEY(mission_id) REFERENCES mission_plans(mission_id)
                );
                CREATE TABLE IF NOT EXISTS mission_outcomes (
                    outcome_id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(mission_id) REFERENCES mission_plans(mission_id)
                );

                CREATE TRIGGER IF NOT EXISTS opportunity_briefs_no_update
                BEFORE UPDATE ON opportunity_briefs BEGIN SELECT RAISE(ABORT, 'opportunity briefs are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS opportunity_briefs_no_delete
                BEFORE DELETE ON opportunity_briefs BEGIN SELECT RAISE(ABORT, 'opportunity briefs are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS mission_plans_no_update
                BEFORE UPDATE ON mission_plans BEGIN SELECT RAISE(ABORT, 'mission plans are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS mission_plans_no_delete
                BEFORE DELETE ON mission_plans BEGIN SELECT RAISE(ABORT, 'mission plans are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS mission_decisions_no_update
                BEFORE UPDATE ON mission_decisions BEGIN SELECT RAISE(ABORT, 'mission decisions are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS mission_decisions_no_delete
                BEFORE DELETE ON mission_decisions BEGIN SELECT RAISE(ABORT, 'mission decisions are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS mission_transitions_no_update
                BEFORE UPDATE ON mission_transitions BEGIN SELECT RAISE(ABORT, 'mission transitions are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS mission_transitions_no_delete
                BEFORE DELETE ON mission_transitions BEGIN SELECT RAISE(ABORT, 'mission transitions are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS mission_step_attempts_no_update
                BEFORE UPDATE ON mission_step_attempts BEGIN SELECT RAISE(ABORT, 'mission step attempts are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS mission_step_attempts_no_delete
                BEFORE DELETE ON mission_step_attempts BEGIN SELECT RAISE(ABORT, 'mission step attempts are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS mission_value_evidence_no_update
                BEFORE UPDATE ON mission_value_evidence BEGIN SELECT RAISE(ABORT, 'mission value evidence is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS mission_value_evidence_no_delete
                BEFORE DELETE ON mission_value_evidence BEGIN SELECT RAISE(ABORT, 'mission value evidence is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS mission_outcomes_no_update
                BEFORE UPDATE ON mission_outcomes BEGIN SELECT RAISE(ABORT, 'mission outcomes are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS mission_outcomes_no_delete
                BEFORE DELETE ON mission_outcomes BEGIN SELECT RAISE(ABORT, 'mission outcomes are immutable'); END;
                """
            )

    # Opportunity briefs -------------------------------------------------
    def add_brief(self, brief: ExpectedValueBrief) -> ExpectedValueBrief:
        with self._connect() as conn:
            existing = conn.execute("SELECT payload_json FROM opportunity_briefs WHERE brief_hash=?", (brief.brief_hash,)).fetchone()
            if existing is not None:
                return opportunity_brief_from_payload(_load(existing["payload_json"], {}))
            conn.execute(
                "INSERT INTO opportunity_briefs VALUES (?, ?, ?, ?, ?)",
                (brief.brief_id, brief.brief_hash, brief.lane.value, _dump(opportunity_brief_payload(brief)), brief.created_at),
            )
        return brief

    def get_brief(self, brief_id: str) -> ExpectedValueBrief:
        with self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM opportunity_briefs WHERE brief_id=?", (brief_id,)).fetchone()
        if row is None:
            raise MissionNotFound(brief_id)
        return opportunity_brief_from_payload(_load(row["payload_json"], {}))

    def list_briefs(self, *, limit: int = 200) -> tuple[ExpectedValueBrief, ...]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload_json FROM opportunity_briefs ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 2000)),)).fetchall()
        return tuple(opportunity_brief_from_payload(_load(row["payload_json"], {})) for row in rows)

    # Plans and decisions ------------------------------------------------
    def add_plan(self, plan: MissionPlan) -> MissionPlan:
        self.get_brief(plan.brief_id)
        with self._connect() as conn:
            existing = conn.execute("SELECT payload_json FROM mission_plans WHERE plan_hash=?", (plan.plan_hash,)).fetchone()
            if existing is not None:
                return mission_plan_from_payload(_load(existing["payload_json"], {}))
            conn.execute(
                "INSERT INTO mission_plans VALUES (?, ?, ?, ?, ?, ?)",
                (plan.mission_id, plan.brief_id, plan.plan_hash, plan.lane.value, _dump(mission_plan_payload(plan)), plan.created_at),
            )
        return plan

    def get_plan(self, mission_id: str) -> MissionPlan:
        with self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM mission_plans WHERE mission_id=?", (mission_id,)).fetchone()
        if row is None:
            raise MissionNotFound(mission_id)
        return mission_plan_from_payload(_load(row["payload_json"], {}))

    def list_plans(self, *, limit: int = 200) -> tuple[MissionPlan, ...]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload_json FROM mission_plans ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 2000)),)).fetchall()
        return tuple(mission_plan_from_payload(_load(row["payload_json"], {})) for row in rows)

    def add_decision(self, decision: MissionDecision) -> MissionDecision:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM mission_decisions WHERE mission_id=?", (decision.mission_id,)).fetchone()
            if row is not None:
                return self._decision_from_row(row)
            conn.execute(
                "INSERT INTO mission_decisions VALUES (?, ?, ?, ?, ?, ?, ?)",
                (decision.decision_id, decision.mission_id, decision.decision.value, decision.principal, decision.channel, decision.reason, decision.decided_at),
            )
        return decision

    def get_decision(self, mission_id: str) -> MissionDecision | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM mission_decisions WHERE mission_id=?", (mission_id,)).fetchone()
        return self._decision_from_row(row) if row else None

    @staticmethod
    def _decision_from_row(row: sqlite3.Row) -> MissionDecision:
        return MissionDecision(
            decision_id=row["decision_id"], mission_id=row["mission_id"], decision=MissionDecisionType(row["decision"]),
            principal=row["principal"], channel=row["channel"], reason=row["reason"], decided_at=row["decided_at"],
        )

    # State transitions ---------------------------------------------------
    def transition(
        self,
        mission_id: str,
        to_status: MissionStatus,
        *,
        principal: str,
        reason: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> MissionTransition:
        self.get_plan(mission_id)
        current = self.current_status(mission_id)
        if current == to_status:
            latest = self.transitions(mission_id, limit=1)
            if latest:
                return latest[0]
        item = MissionTransition(
            mission_id=mission_id,
            from_status=current,
            to_status=to_status,
            principal=principal,
            reason=reason,
            metadata=dict(metadata or {}),
            created_at=utc_now(),
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO mission_transitions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (item.transition_id, item.mission_id, item.from_status.value if item.from_status else None, item.to_status.value,
                 item.principal, item.reason, _dump(dict(item.metadata)), item.created_at),
            )
        return item

    def current_status(self, mission_id: str) -> MissionStatus:
        self.get_plan(mission_id)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT to_status FROM mission_transitions WHERE mission_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (mission_id,),
            ).fetchone()
        return MissionStatus(row["to_status"]) if row else MissionStatus.DRAFT

    def transitions(self, mission_id: str, *, limit: int = 500) -> tuple[MissionTransition, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM mission_transitions WHERE mission_id=? ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (mission_id, max(1, min(limit, 5000))),
            ).fetchall()
        return tuple(MissionTransition(
            transition_id=row["transition_id"], mission_id=row["mission_id"],
            from_status=MissionStatus(row["from_status"]) if row["from_status"] else None,
            to_status=MissionStatus(row["to_status"]), principal=row["principal"], reason=row["reason"],
            metadata=_load(row["metadata_json"], {}), created_at=row["created_at"],
        ) for row in rows)

    # Step attempts -------------------------------------------------------
    def add_attempt(self, item: MissionStepAttempt) -> MissionStepAttempt:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO mission_step_attempts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (item.attempt_id, item.mission_id, item.step_id, item.attempt_number, item.status.value,
                 item.action_id, item.approval_id, _dump(item.output) if item.output is not None else None,
                 item.error, item.failure_fingerprint, item.estimated_cost_usd, _dump(dict(item.metadata)),
                 item.started_at, item.completed_at),
            )
        return item

    def attempts(self, mission_id: str, *, step_id: str | None = None, limit: int = 1000) -> tuple[MissionStepAttempt, ...]:
        query = "SELECT * FROM mission_step_attempts WHERE mission_id=?"
        params: list[Any] = [mission_id]
        if step_id:
            query += " AND step_id=?"
            params.append(step_id)
        query += " ORDER BY started_at ASC, rowid ASC LIMIT ?"
        params.append(max(1, min(limit, 10000)))
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return tuple(self._attempt_from_row(row) for row in rows)

    def latest_attempt(self, mission_id: str, step_id: str) -> MissionStepAttempt | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM mission_step_attempts WHERE mission_id=? AND step_id=? ORDER BY started_at DESC, rowid DESC LIMIT 1",
                (mission_id, step_id),
            ).fetchone()
        return self._attempt_from_row(row) if row else None

    @staticmethod
    def _attempt_from_row(row: sqlite3.Row) -> MissionStepAttempt:
        return MissionStepAttempt(
            attempt_id=row["attempt_id"], mission_id=row["mission_id"], step_id=row["step_id"],
            attempt_number=int(row["attempt_number"]), status=MissionStepStatus(row["status"]), action_id=row["action_id"],
            approval_id=row["approval_id"], output=_load(row["output_json"]), error=row["error"],
            failure_fingerprint=row["failure_fingerprint"], estimated_cost_usd=float(row["estimated_cost_usd"]),
            metadata=_load(row["metadata_json"], {}), started_at=row["started_at"], completed_at=row["completed_at"],
        )

    # Value and outcome evidence -----------------------------------------
    def add_value_evidence(self, item: MissionValueEvidence) -> MissionValueEvidence:
        self.get_plan(item.mission_id)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO mission_value_evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (item.evidence_id, item.mission_id, item.kind.value, item.description, item.source, item.amount_usd,
                 item.external_reference, item.related_evidence_id, item.verified_by, _dump(dict(item.metadata)), item.observed_at),
            )
        return item

    def get_value_evidence(self, evidence_id: str) -> MissionValueEvidence:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM mission_value_evidence WHERE evidence_id=?", (evidence_id,)).fetchone()
        if row is None:
            raise MissionNotFound(evidence_id)
        return self._value_from_row(row)

    def value_evidence(self, mission_id: str) -> tuple[MissionValueEvidence, ...]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM mission_value_evidence WHERE mission_id=? ORDER BY observed_at ASC, rowid ASC", (mission_id,)).fetchall()
        return tuple(self._value_from_row(row) for row in rows)

    @staticmethod
    def _value_from_row(row: sqlite3.Row) -> MissionValueEvidence:
        return MissionValueEvidence(
            evidence_id=row["evidence_id"], mission_id=row["mission_id"], kind=MissionValueKind(row["kind"]),
            description=row["description"], source=row["source"], amount_usd=float(row["amount_usd"]) if row["amount_usd"] is not None else None,
            external_reference=row["external_reference"], related_evidence_id=row["related_evidence_id"],
            verified_by=row["verified_by"], metadata=_load(row["metadata_json"], {}), observed_at=row["observed_at"],
        )

    def add_outcome(self, outcome: MissionOutcome) -> MissionOutcome:
        payload = {
            **asdict(outcome),
            "state": outcome.state.value,
            "evidence_ids": list(outcome.evidence_ids),
            "lessons": list(outcome.lessons),
        }
        with self._connect() as conn:
            conn.execute("INSERT INTO mission_outcomes VALUES (?, ?, ?, ?)", (outcome.outcome_id, outcome.mission_id, _dump(payload), outcome.created_at))
        return outcome

    def latest_outcome(self, mission_id: str) -> MissionOutcome | None:
        with self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM mission_outcomes WHERE mission_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1", (mission_id,)).fetchone()
        if row is None:
            return None
        data = _load(row["payload_json"], {})
        return MissionOutcome(
            outcome_id=data["outcome_id"], mission_id=data["mission_id"], state=MissionOutcomeState(data["state"]),
            achieved=bool(data["achieved"]), summary=data["summary"], claimed_value_usd=float(data["claimed_value_usd"]),
            realized_revenue_usd=float(data["realized_revenue_usd"]), verified_revenue_usd=float(data["verified_revenue_usd"]),
            evidence_ids=tuple(data.get("evidence_ids") or ()), lessons=tuple(data.get("lessons") or ()),
            metadata=dict(data.get("metadata") or {}), created_at=data["created_at"],
        )

    def mission_view(self, mission_id: str) -> dict[str, Any]:
        plan = self.get_plan(mission_id)
        brief = self.get_brief(plan.brief_id)
        attempts = self.attempts(mission_id)
        decision = self.get_decision(mission_id)
        outcome = self.latest_outcome(mission_id)
        return {
            "plan": mission_plan_payload(plan),
            "brief": opportunity_brief_payload(brief),
            "status": self.current_status(mission_id).value,
            "decision": asdict(decision) | {"decision": decision.decision.value} if decision else None,
            "transitions": [asdict(item) | {"from_status": item.from_status.value if item.from_status else None, "to_status": item.to_status.value} for item in self.transitions(mission_id)],
            "attempts": [asdict(item) | {"status": item.status.value} for item in attempts],
            "value_evidence": [asdict(item) | {"kind": item.kind.value} for item in self.value_evidence(mission_id)],
            "outcome": asdict(outcome) | {"state": outcome.state.value} if outcome else None,
        }

    def status(self) -> dict[str, Any]:
        plans = self.list_plans(limit=5000)
        counts: dict[str, int] = {item.value: 0 for item in MissionStatus}
        for plan in plans:
            counts[self.current_status(plan.mission_id).value] += 1
        return {"briefs": len(self.list_briefs(limit=5000)), "missions": len(plans), "by_status": counts}
