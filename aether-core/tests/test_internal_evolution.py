from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from aether.contracts import (
    EvolutionCheckKind, EvolutionCheckResult, EvolutionCommand, EvolutionDecisionType,
    EvolutionEvaluation, EvolutionLearning, EvolutionTargetType, EventType, PromotionReceipt,
)
from aether.events import Event
from aether.evolution import (
    EvolutionBlocked, EvolutionDecisionConflict, InternalEvolutionEngine,
    SQLiteEvolutionStore, capability_gap, trigger_from_event,
)


def _commands():
    return (
        EvolutionCommand(("{python}", "-m", "unittest", "discover", "-s", "tests"), EvolutionCheckKind.DETERMINISTIC, "unit"),
        EvolutionCommand(("{python}", "-m", "unittest", "discover", "-s", "heldout"), EvolutionCheckKind.HELDOUT, "heldout"),
    )


def _candidate(engine: InternalEvolutionEngine, trigger_id: str, *, retry_reason: str | None = None, target: str = "src/module.py"):
    unit, heldout = _commands()
    return engine.propose_candidate(
        trigger_id=trigger_id,
        target_type=EvolutionTargetType.CODE,
        target_path=target,
        baseline_content="def answer():\n    return 41\n",
        candidate_content="def answer():\n    return 42\n",
        rationale="Correct the bounded capability behavior.",
        generator_id="generator.test",
        deterministic_checks=(unit,),
        heldout_checks=(heldout,),
        retry_reason=retry_reason,
    )


class _Sandbox:
    def __init__(self, passed: bool = True):
        self.passed = passed

    async def evaluate(self, candidate):
        unit, heldout = _commands()
        checks = (
            EvolutionCheckResult("unit", unit.kind, "baseline", False, 1, 0.1),
            EvolutionCheckResult("heldout", heldout.kind, "baseline", False, 1, 0.1),
            EvolutionCheckResult("unit", unit.kind, "candidate", self.passed, 0 if self.passed else 1, 0.1),
            EvolutionCheckResult("heldout", heldout.kind, "candidate", self.passed, 0 if self.passed else 1, 0.1),
        )
        return EvolutionEvaluation(
            candidate_id=candidate.candidate_id,
            sandbox_id="sandbox.test",
            baseline_score=0.0,
            candidate_score=1.0 if self.passed else 0.0,
            improvement=1.0 if self.passed else 0.0,
            regression_count=0,
            checks=checks,
            passed=self.passed,
            blockers=() if self.passed else ("candidate failed",),
        )


class _Promoter:
    def __init__(self):
        self.promotions = 0
        self.rollbacks = 0

    async def promote(self, candidate):
        self.promotions += 1
        return PromotionReceipt(candidate.target_path, candidate.baseline_hash, candidate.candidate_hash, "/backup/module.py")

    async def rollback(self, lineage):
        self.rollbacks += 1


def test_failure_event_intake_preserves_event_evidence() -> None:
    event = Event(
        event_type=EventType.ACTION_FAILED,
        actor="action.path",
        payload={"error": "write failed", "target": "tool", "failure_fingerprint": "fp-123"},
    )
    trigger = trigger_from_event(event)
    assert trigger is not None
    assert trigger.fingerprint == "fp-123"
    assert trigger.evidence_ids == (event.event_id,)
    assert trigger.metadata["event_type"] == EventType.ACTION_FAILED
    assert trigger_from_event(Event("cognition.completed", "test")) is None


def test_prior_learning_is_recalled_when_trigger_is_registered(tmp_path: Path) -> None:
    store = SQLiteEvolutionStore(tmp_path / "evolution.sqlite3")
    store.add_learning(EvolutionLearning(fingerprint="same-failure", outcome="rejected", summary="Previous patch regressed held-out behavior."))
    engine = InternalEvolutionEngine(store)
    trigger = engine.register_trigger(capability_gap(summary="Gap", target="module.py"))
    # Force a known fingerprint to verify exact recall path.
    trigger2 = engine.register_trigger(replace(trigger, trigger_id="evo-trigger.second", fingerprint="same-failure", prior_learning_ids=()))
    assert len(trigger2.prior_learning_ids) == 1
    assert store.learnings_for_fingerprint("same-failure")[0].summary.startswith("Previous patch")


def test_protected_identity_and_northstar_cannot_be_candidates(tmp_path: Path) -> None:
    engine = InternalEvolutionEngine(SQLiteEvolutionStore(tmp_path / "evolution.sqlite3"))
    trigger = engine.register_trigger(capability_gap(summary="Change identity", target="src/aether/dna/north_star.yaml"))
    with pytest.raises(EvolutionBlocked, match="protected"):
        _candidate(engine, trigger.trigger_id, target="src/aether/dna/north_star.yaml")


def test_same_failed_candidate_requires_explicit_retry_reason(tmp_path: Path) -> None:
    store = SQLiteEvolutionStore(tmp_path / "evolution.sqlite3")
    engine = InternalEvolutionEngine(store)
    trigger = engine.register_trigger(capability_gap(summary="Broken answer", target="src/module.py"))
    first = _candidate(engine, trigger.trigger_id)
    asyncio.run(engine.evaluate(first.candidate_id, _Sandbox(False)))
    with pytest.raises(EvolutionBlocked, match="same failed candidate"):
        _candidate(engine, trigger.trigger_id)
    retried = _candidate(engine, trigger.trigger_id, retry_reason="The held-out fixture was corrected and is materially different.")
    assert retried.candidate_id != first.candidate_id
    assert retried.retry_reason
    successful = asyncio.run(engine.evaluate(retried.candidate_id, _Sandbox(True)))
    assert successful.passed is True


def test_promotion_requires_passed_evaluation_and_trusted_operator(tmp_path: Path) -> None:
    store = SQLiteEvolutionStore(tmp_path / "evolution.sqlite3")
    engine = InternalEvolutionEngine(store)
    trigger = engine.register_trigger(capability_gap(summary="Broken answer", target="src/module.py"))
    candidate = _candidate(engine, trigger.trigger_id)
    promoter = _Promoter()
    with pytest.raises(EvolutionBlocked, match="not been evaluated"):
        asyncio.run(engine.decide(
            candidate.candidate_id, approved=True, principal="founder", channel="test",
            reason="Promote after verified deterministic and held-out checks.", promoter=promoter,
        ))
    asyncio.run(engine.evaluate(candidate.candidate_id, _Sandbox(True)))
    with pytest.raises(EvolutionBlocked, match="not trusted"):
        asyncio.run(engine.decide(
            candidate.candidate_id, approved=True, principal="model", channel="model",
            reason="The model approves its own generated candidate.", promoter=promoter,
        ))
    promoted = asyncio.run(engine.decide(
        candidate.candidate_id, approved=True, principal="founder", channel="test",
        reason="Deterministic and held-out checks show measurable improvement with zero regressions.", promoter=promoter,
    ))
    assert promoted.status.value == "promoted"
    assert promoter.promotions == 1
    assert store.get_decision(candidate.candidate_id).decision == EvolutionDecisionType.PROMOTE


def test_reject_is_terminal_and_records_learning(tmp_path: Path) -> None:
    store = SQLiteEvolutionStore(tmp_path / "evolution.sqlite3")
    engine = InternalEvolutionEngine(store)
    trigger = engine.register_trigger(capability_gap(summary="Broken answer", target="src/module.py"))
    candidate = _candidate(engine, trigger.trigger_id)
    rejected = asyncio.run(engine.decide(
        candidate.candidate_id, approved=False, principal="founder", channel="test",
        reason="The proposed change does not preserve the intended architecture boundary.",
    ))
    assert rejected.status.value == "rejected"
    assert store.learnings_for_fingerprint(trigger.fingerprint)[0].outcome == "rejected"
    with pytest.raises(EvolutionDecisionConflict):
        asyncio.run(engine.decide(
            candidate.candidate_id, approved=True, principal="founder", channel="test",
            reason="Contradictory terminal decision should be rejected.", promoter=_Promoter(),
        ))


def test_promoted_lineage_can_be_rolled_back_once(tmp_path: Path) -> None:
    store = SQLiteEvolutionStore(tmp_path / "evolution.sqlite3")
    engine = InternalEvolutionEngine(store)
    trigger = engine.register_trigger(capability_gap(summary="Broken answer", target="src/module.py"))
    candidate = _candidate(engine, trigger.trigger_id)
    promoter = _Promoter()
    asyncio.run(engine.evaluate(candidate.candidate_id, _Sandbox(True)))
    promoted = asyncio.run(engine.decide(
        candidate.candidate_id, approved=True, principal="founder", channel="test",
        reason="Verified improvement is ready for bounded promotion.", promoter=promoter,
    ))
    lineage = store.get_lineage(promoted.lineage_id)
    rolled_back = asyncio.run(engine.rollback(
        lineage.lineage_id, principal="founder", channel="test",
        reason="A post-promotion operational signal requires rollback.", promoter=promoter,
    ))
    assert rolled_back.rolled_back_at
    assert store.get_candidate(candidate.candidate_id).status.value == "rolled-back"
    assert promoter.rollbacks == 1
    again = asyncio.run(engine.rollback(
        lineage.lineage_id, principal="founder", channel="test",
        reason="Idempotent rollback request should not execute twice.", promoter=promoter,
    ))
    assert again.rolled_back_at == rolled_back.rolled_back_at
    assert promoter.rollbacks == 1


def test_evolution_ledger_tables_are_immutable(tmp_path: Path) -> None:
    store = SQLiteEvolutionStore(tmp_path / "evolution.sqlite3")
    engine = InternalEvolutionEngine(store)
    trigger = engine.register_trigger(capability_gap(summary="Broken answer", target="src/module.py"))
    candidate = _candidate(engine, trigger.trigger_id)
    with sqlite3.connect(store.path) as conn:
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            conn.execute("UPDATE evolution_candidates SET rationale='tampered' WHERE candidate_id=?", (candidate.candidate_id,))
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            conn.execute("DELETE FROM evolution_triggers WHERE trigger_id=?", (trigger.trigger_id,))
