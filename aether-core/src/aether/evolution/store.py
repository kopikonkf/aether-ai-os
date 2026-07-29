"""Append-only SQLite lineage store for internal evolution."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Iterable

from aether.contracts.evolution import (
    EvolutionCandidate, EvolutionCandidateStatus, EvolutionCheckKind, EvolutionCheckResult,
    EvolutionCommand, EvolutionDecision, EvolutionDecisionType, EvolutionEvaluation,
    EvolutionLearning, EvolutionLineage, EvolutionTargetType, EvolutionTrigger,
    EvolutionTriggerType,
)
from aether.utils.time import utc_now


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


class EvolutionNotFound(KeyError):
    pass


class EvolutionDecisionConflict(RuntimeError):
    pass


class SQLiteEvolutionStore:
    store_id = "aether.evolution.sqlite"

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
                CREATE TABLE IF NOT EXISTS evolution_triggers (
                    trigger_id TEXT PRIMARY KEY,
                    trigger_type TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    prior_learning_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_evolution_trigger_fingerprint
                    ON evolution_triggers(fingerprint, created_at DESC);

                CREATE TABLE IF NOT EXISTS evolution_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    trigger_id TEXT NOT NULL REFERENCES evolution_triggers(trigger_id),
                    trigger_fingerprint TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_path TEXT NOT NULL,
                    baseline_hash TEXT NOT NULL,
                    candidate_hash TEXT NOT NULL,
                    baseline_content TEXT NOT NULL,
                    candidate_content TEXT NOT NULL,
                    diff_text TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    generator_id TEXT NOT NULL,
                    deterministic_json TEXT NOT NULL,
                    heldout_json TEXT NOT NULL,
                    retry_reason TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    semantic_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS idx_evolution_candidate_trigger
                    ON evolution_candidates(trigger_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_evolution_candidate_fingerprint
                    ON evolution_candidates(trigger_fingerprint, created_at DESC);

                CREATE TABLE IF NOT EXISTS evolution_evaluations (
                    evaluation_id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL UNIQUE REFERENCES evolution_candidates(candidate_id),
                    sandbox_id TEXT NOT NULL,
                    baseline_score REAL NOT NULL,
                    candidate_score REAL NOT NULL,
                    improvement REAL NOT NULL,
                    regression_count INTEGER NOT NULL,
                    checks_json TEXT NOT NULL,
                    passed INTEGER NOT NULL,
                    blockers_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS evolution_decisions (
                    decision_id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL UNIQUE REFERENCES evolution_candidates(candidate_id),
                    decision TEXT NOT NULL,
                    principal TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    decided_at TEXT NOT NULL,
                    lineage_id TEXT
                );

                CREATE TABLE IF NOT EXISTS evolution_lineage (
                    lineage_id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL UNIQUE REFERENCES evolution_candidates(candidate_id),
                    target_path TEXT NOT NULL,
                    parent_hash TEXT NOT NULL,
                    promoted_hash TEXT NOT NULL,
                    backup_path TEXT NOT NULL,
                    principal TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    promoted_at TEXT NOT NULL,
                    rolled_back_at TEXT,
                    rollback_principal TEXT,
                    rollback_reason TEXT
                );

                CREATE TABLE IF NOT EXISTS evolution_rollbacks (
                    rollback_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lineage_id TEXT NOT NULL UNIQUE REFERENCES evolution_lineage(lineage_id),
                    principal TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    rolled_back_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS evolution_learnings (
                    learning_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    candidate_id TEXT,
                    lineage_id TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_evolution_learning_fingerprint
                    ON evolution_learnings(fingerprint, created_at DESC);

                CREATE TRIGGER IF NOT EXISTS evolution_triggers_no_update BEFORE UPDATE ON evolution_triggers
                BEGIN SELECT RAISE(ABORT, 'evolution ledger is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS evolution_triggers_no_delete BEFORE DELETE ON evolution_triggers
                BEGIN SELECT RAISE(ABORT, 'evolution ledger is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS evolution_candidates_no_update BEFORE UPDATE ON evolution_candidates
                BEGIN SELECT RAISE(ABORT, 'evolution ledger is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS evolution_candidates_no_delete BEFORE DELETE ON evolution_candidates
                BEGIN SELECT RAISE(ABORT, 'evolution ledger is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS evolution_evaluations_no_update BEFORE UPDATE ON evolution_evaluations
                BEGIN SELECT RAISE(ABORT, 'evolution ledger is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS evolution_evaluations_no_delete BEFORE DELETE ON evolution_evaluations
                BEGIN SELECT RAISE(ABORT, 'evolution ledger is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS evolution_decisions_no_update BEFORE UPDATE ON evolution_decisions
                BEGIN SELECT RAISE(ABORT, 'evolution ledger is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS evolution_decisions_no_delete BEFORE DELETE ON evolution_decisions
                BEGIN SELECT RAISE(ABORT, 'evolution ledger is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS evolution_lineage_no_update BEFORE UPDATE ON evolution_lineage
                BEGIN SELECT RAISE(ABORT, 'evolution lineage is append-only; use rollback records'); END;
                CREATE TRIGGER IF NOT EXISTS evolution_lineage_no_delete BEFORE DELETE ON evolution_lineage
                BEGIN SELECT RAISE(ABORT, 'evolution ledger is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS evolution_rollbacks_no_update BEFORE UPDATE ON evolution_rollbacks
                BEGIN SELECT RAISE(ABORT, 'evolution ledger is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS evolution_rollbacks_no_delete BEFORE DELETE ON evolution_rollbacks
                BEGIN SELECT RAISE(ABORT, 'evolution ledger is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS evolution_learnings_no_update BEFORE UPDATE ON evolution_learnings
                BEGIN SELECT RAISE(ABORT, 'evolution ledger is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS evolution_learnings_no_delete BEFORE DELETE ON evolution_learnings
                BEGIN SELECT RAISE(ABORT, 'evolution ledger is immutable'); END;
                """
            )

    def add_trigger(self, trigger: EvolutionTrigger) -> EvolutionTrigger:
        normalized = replace(trigger, created_at=trigger.created_at or utc_now())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO evolution_triggers VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    normalized.trigger_id, normalized.trigger_type.value, normalized.fingerprint,
                    normalized.summary, _json(normalized.evidence_ids), _json(normalized.prior_learning_ids),
                    _json(dict(normalized.metadata)), normalized.created_at,
                ),
            )
        return normalized

    def get_trigger(self, trigger_id: str) -> EvolutionTrigger:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM evolution_triggers WHERE trigger_id=?", (trigger_id,)).fetchone()
        if row is None:
            raise EvolutionNotFound(trigger_id)
        return self._row_trigger(row)

    def list_triggers(self, limit: int = 100) -> tuple[EvolutionTrigger, ...]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM evolution_triggers ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return tuple(self._row_trigger(row) for row in rows)

    def add_candidate(self, candidate: EvolutionCandidate, semantic_hash: str) -> EvolutionCandidate:
        normalized = replace(candidate, created_at=candidate.created_at or utc_now())
        try:
            with self._connect() as conn:
                conn.execute(
                    """INSERT INTO evolution_candidates VALUES
                    (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        normalized.candidate_id, normalized.trigger_id, normalized.trigger_fingerprint,
                        normalized.target_type.value, normalized.target_path, normalized.baseline_hash,
                        normalized.candidate_hash, normalized.baseline_content, normalized.candidate_content,
                        normalized.diff, normalized.rationale, normalized.generator_id,
                        _json([asdict(item) for item in normalized.deterministic_checks]),
                        _json([asdict(item) for item in normalized.heldout_checks]),
                        normalized.retry_reason, _json(dict(normalized.metadata)), normalized.created_at,
                        semantic_hash,
                    ),
                )
        except sqlite3.IntegrityError:
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM evolution_candidates WHERE semantic_hash=?", (semantic_hash,)).fetchone()
            if row is None:
                raise
            return self._row_candidate(row)
        return normalized

    def get_candidate(self, candidate_id: str) -> EvolutionCandidate:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM evolution_candidates WHERE candidate_id=?", (candidate_id,)).fetchone()
        if row is None:
            raise EvolutionNotFound(candidate_id)
        return self._decorate_candidate(self._row_candidate(row))

    def list_candidates(self, limit: int = 100) -> tuple[EvolutionCandidate, ...]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM evolution_candidates ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return tuple(self._decorate_candidate(self._row_candidate(row)) for row in rows)

    def candidates_for_fingerprint(self, fingerprint: str) -> tuple[EvolutionCandidate, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM evolution_candidates WHERE trigger_fingerprint=? ORDER BY created_at DESC", (fingerprint,)
            ).fetchall()
        return tuple(self._decorate_candidate(self._row_candidate(row)) for row in rows)

    def add_evaluation(self, evaluation: EvolutionEvaluation) -> EvolutionEvaluation:
        normalized = replace(evaluation, created_at=evaluation.created_at or utc_now())
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO evolution_evaluations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        normalized.evaluation_id, normalized.candidate_id, normalized.sandbox_id,
                        normalized.baseline_score, normalized.candidate_score, normalized.improvement,
                        normalized.regression_count, _json([asdict(item) for item in normalized.checks]),
                        int(normalized.passed), _json(normalized.blockers), _json(dict(normalized.metadata)),
                        normalized.created_at,
                    ),
                )
        except sqlite3.IntegrityError:
            existing = self.get_evaluation(normalized.candidate_id)
            if existing is None:
                raise
            return existing
        return normalized

    def get_evaluation(self, candidate_id: str) -> EvolutionEvaluation | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM evolution_evaluations WHERE candidate_id=?", (candidate_id,)).fetchone()
        return self._row_evaluation(row) if row else None

    def decide(self, decision: EvolutionDecision) -> EvolutionDecision:
        normalized = replace(decision, decided_at=decision.decided_at or utc_now())
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO evolution_decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        normalized.decision_id, normalized.candidate_id, normalized.decision.value,
                        normalized.principal, normalized.channel, normalized.reason, normalized.decided_at,
                        normalized.lineage_id,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            existing = self.get_decision(normalized.candidate_id)
            if existing and existing.decision == normalized.decision:
                return existing
            raise EvolutionDecisionConflict(f"candidate {normalized.candidate_id} already has a terminal decision") from exc
        return normalized

    def get_decision(self, candidate_id: str) -> EvolutionDecision | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM evolution_decisions WHERE candidate_id=?", (candidate_id,)).fetchone()
        return self._row_decision(row) if row else None

    def add_lineage(self, lineage: EvolutionLineage) -> EvolutionLineage:
        normalized = replace(lineage, promoted_at=lineage.promoted_at or utc_now())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO evolution_lineage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL)",
                (
                    normalized.lineage_id, normalized.candidate_id, normalized.target_path,
                    normalized.parent_hash, normalized.promoted_hash, normalized.backup_path,
                    normalized.principal, normalized.reason, normalized.promoted_at,
                ),
            )
        return normalized

    def get_lineage(self, lineage_id: str) -> EvolutionLineage:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM evolution_lineage WHERE lineage_id=?", (lineage_id,)).fetchone()
            rollback = conn.execute("SELECT * FROM evolution_rollbacks WHERE lineage_id=?", (lineage_id,)).fetchone()
        if row is None:
            raise EvolutionNotFound(lineage_id)
        return self._row_lineage(row, rollback)

    def lineage_for_candidate(self, candidate_id: str) -> EvolutionLineage | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM evolution_lineage WHERE candidate_id=?", (candidate_id,)).fetchone()
            rollback = conn.execute("SELECT * FROM evolution_rollbacks WHERE lineage_id=?", (row["lineage_id"],)).fetchone() if row else None
        return self._row_lineage(row, rollback) if row else None

    def add_rollback(self, lineage_id: str, *, principal: str, reason: str) -> EvolutionLineage:
        rolled_back_at = utc_now()
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO evolution_rollbacks(lineage_id, principal, reason, rolled_back_at) VALUES (?, ?, ?, ?)",
                    (lineage_id, principal, reason, rolled_back_at),
                )
        except sqlite3.IntegrityError as exc:
            raise EvolutionDecisionConflict(f"lineage {lineage_id} already rolled back") from exc
        return self.get_lineage(lineage_id)

    def add_learning(self, learning: EvolutionLearning) -> EvolutionLearning:
        normalized = replace(learning, created_at=learning.created_at or utc_now())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO evolution_learnings VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    normalized.learning_id, normalized.fingerprint, normalized.outcome, normalized.summary,
                    normalized.candidate_id, normalized.lineage_id, _json(dict(normalized.metadata)),
                    normalized.created_at,
                ),
            )
        return normalized

    def learnings_for_fingerprint(self, fingerprint: str, limit: int = 20) -> tuple[EvolutionLearning, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM evolution_learnings WHERE fingerprint=? ORDER BY created_at DESC LIMIT ?",
                (fingerprint, limit),
            ).fetchall()
        return tuple(self._row_learning(row) for row in rows)

    def _decorate_candidate(self, candidate: EvolutionCandidate) -> EvolutionCandidate:
        evaluation = self.get_evaluation(candidate.candidate_id)
        decision = self.get_decision(candidate.candidate_id)
        lineage = self.lineage_for_candidate(candidate.candidate_id)
        status = EvolutionCandidateStatus.PROPOSED
        if evaluation and evaluation.passed:
            status = EvolutionCandidateStatus.VERIFIED
        if decision and decision.decision == EvolutionDecisionType.REJECT:
            status = EvolutionCandidateStatus.REJECTED
        if decision and decision.decision == EvolutionDecisionType.PROMOTE:
            status = EvolutionCandidateStatus.PROMOTED
        if lineage and lineage.rolled_back_at:
            status = EvolutionCandidateStatus.ROLLED_BACK
        return replace(
            candidate, status=status,
            evaluation_id=evaluation.evaluation_id if evaluation else None,
            decision_id=decision.decision_id if decision else None,
            lineage_id=lineage.lineage_id if lineage else None,
        )

    @staticmethod
    def _row_trigger(row: sqlite3.Row) -> EvolutionTrigger:
        return EvolutionTrigger(
            trigger_id=row["trigger_id"], trigger_type=EvolutionTriggerType(row["trigger_type"]),
            fingerprint=row["fingerprint"], summary=row["summary"],
            evidence_ids=tuple(json.loads(row["evidence_json"])),
            prior_learning_ids=tuple(json.loads(row["prior_learning_json"])),
            metadata=json.loads(row["metadata_json"]), created_at=row["created_at"],
        )

    @staticmethod
    def _commands(raw: str) -> tuple[EvolutionCommand, ...]:
        return tuple(EvolutionCommand(
            argv=tuple(item["argv"]), kind=EvolutionCheckKind(item["kind"]), name=item["name"],
            timeout_seconds=int(item.get("timeout_seconds", 120)),
        ) for item in json.loads(raw))

    def _row_candidate(self, row: sqlite3.Row) -> EvolutionCandidate:
        return EvolutionCandidate(
            candidate_id=row["candidate_id"], trigger_id=row["trigger_id"],
            trigger_fingerprint=row["trigger_fingerprint"], target_type=EvolutionTargetType(row["target_type"]),
            target_path=row["target_path"], baseline_hash=row["baseline_hash"], candidate_hash=row["candidate_hash"],
            baseline_content=row["baseline_content"], candidate_content=row["candidate_content"], diff=row["diff_text"],
            rationale=row["rationale"], generator_id=row["generator_id"],
            deterministic_checks=self._commands(row["deterministic_json"]),
            heldout_checks=self._commands(row["heldout_json"]), retry_reason=row["retry_reason"],
            metadata=json.loads(row["metadata_json"]), created_at=row["created_at"],
        )

    @staticmethod
    def _row_evaluation(row: sqlite3.Row) -> EvolutionEvaluation:
        checks = tuple(EvolutionCheckResult(
            name=item["name"], kind=EvolutionCheckKind(item["kind"]), phase=item["phase"],
            passed=bool(item["passed"]), exit_code=int(item["exit_code"]),
            duration_seconds=float(item["duration_seconds"]), stdout=item.get("stdout", ""), stderr=item.get("stderr", ""),
        ) for item in json.loads(row["checks_json"]))
        return EvolutionEvaluation(
            evaluation_id=row["evaluation_id"], candidate_id=row["candidate_id"], sandbox_id=row["sandbox_id"],
            baseline_score=float(row["baseline_score"]), candidate_score=float(row["candidate_score"]),
            improvement=float(row["improvement"]), regression_count=int(row["regression_count"]), checks=checks,
            passed=bool(row["passed"]), blockers=tuple(json.loads(row["blockers_json"])),
            metadata=json.loads(row["metadata_json"]), created_at=row["created_at"],
        )

    @staticmethod
    def _row_decision(row: sqlite3.Row) -> EvolutionDecision:
        return EvolutionDecision(
            decision_id=row["decision_id"], candidate_id=row["candidate_id"],
            decision=EvolutionDecisionType(row["decision"]), principal=row["principal"], channel=row["channel"],
            reason=row["reason"], decided_at=row["decided_at"], lineage_id=row["lineage_id"],
        )

    @staticmethod
    def _row_lineage(row: sqlite3.Row, rollback: sqlite3.Row | None) -> EvolutionLineage:
        return EvolutionLineage(
            lineage_id=row["lineage_id"], candidate_id=row["candidate_id"], target_path=row["target_path"],
            parent_hash=row["parent_hash"], promoted_hash=row["promoted_hash"], backup_path=row["backup_path"],
            principal=row["principal"], reason=row["reason"], promoted_at=row["promoted_at"],
            rolled_back_at=rollback["rolled_back_at"] if rollback else None,
            rollback_principal=rollback["principal"] if rollback else None,
            rollback_reason=rollback["reason"] if rollback else None,
        )

    @staticmethod
    def _row_learning(row: sqlite3.Row) -> EvolutionLearning:
        return EvolutionLearning(
            learning_id=row["learning_id"], fingerprint=row["fingerprint"], outcome=row["outcome"],
            summary=row["summary"], candidate_id=row["candidate_id"], lineage_id=row["lineage_id"],
            metadata=json.loads(row["metadata_json"]), created_at=row["created_at"],
        )
