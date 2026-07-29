from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from aether.contracts import EvolutionCheckKind, EvolutionCommand, EvolutionTargetType
from aether.evolution import InternalEvolutionEngine, SQLiteEvolutionStore, capability_gap
from aether_gateway.evolution import EvolutionWorkspaceError, LocalArtifactPromoter, LocalEvolutionSandbox


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / "tests").mkdir(parents=True)
    (workspace / "heldout").mkdir()
    (workspace / "calculator.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (workspace / "tests" / "test_add.py").write_text(
        "import unittest\nfrom calculator import add\n"
        "class AddTest(unittest.TestCase):\n"
        "    def test_positive(self): self.assertEqual(add(2, 3), 5)\n",
        encoding="utf-8",
    )
    (workspace / "heldout" / "test_edge.py").write_text(
        "import unittest\nfrom calculator import add\n"
        "class EdgeTest(unittest.TestCase):\n"
        "    def test_zero(self): self.assertEqual(add(0, 1), 1)\n",
        encoding="utf-8",
    )
    return workspace


def _candidate(tmp_path: Path):
    workspace = _workspace(tmp_path)
    store = SQLiteEvolutionStore(tmp_path / "evolution.sqlite3")
    engine = InternalEvolutionEngine(store)
    trigger = engine.register_trigger(capability_gap(summary="Addition returns subtraction", target="calculator.py"))
    candidate = engine.propose_candidate(
        trigger_id=trigger.trigger_id,
        target_type=EvolutionTargetType.CODE,
        target_path="calculator.py",
        baseline_content=(workspace / "calculator.py").read_text(encoding="utf-8"),
        candidate_content="def add(a, b):\n    return a + b\n",
        rationale="Correct the arithmetic implementation.",
        generator_id="generator.test",
        deterministic_checks=(EvolutionCommand(
            ("{python}", "-m", "unittest", "discover", "-s", "tests"),
            EvolutionCheckKind.DETERMINISTIC, "unit",
        ),),
        heldout_checks=(EvolutionCommand(
            ("{python}", "-m", "unittest", "discover", "-s", "heldout"),
            EvolutionCheckKind.HELDOUT, "heldout",
        ),),
    )
    return workspace, store, engine, candidate


def test_local_sandbox_evaluates_baseline_and_candidate_then_promotes_and_rolls_back(tmp_path: Path) -> None:
    workspace, store, engine, candidate = _candidate(tmp_path)
    sandbox = LocalEvolutionSandbox(workspace, tmp_path / "sandboxes")
    promoter = LocalArtifactPromoter(workspace, tmp_path / "backups")
    evaluation = asyncio.run(engine.evaluate(candidate.candidate_id, sandbox))
    assert evaluation.passed is True
    assert evaluation.baseline_score == 0.0
    assert evaluation.candidate_score == 1.0
    assert {item.phase for item in evaluation.checks} == {"baseline", "candidate"}
    promoted = asyncio.run(engine.decide(
        candidate.candidate_id, approved=True, principal="founder", channel="test",
        reason="Both deterministic and held-out suites pass with measurable improvement.", promoter=promoter,
    ))
    assert "return a + b" in (workspace / "calculator.py").read_text(encoding="utf-8")
    lineage = store.get_lineage(promoted.lineage_id)
    asyncio.run(engine.rollback(
        lineage.lineage_id, principal="founder", channel="test",
        reason="Rollback adapter verification after successful promotion.", promoter=promoter,
    ))
    assert "return a - b" in (workspace / "calculator.py").read_text(encoding="utf-8")


def test_local_sandbox_rejects_arbitrary_process_commands(tmp_path: Path) -> None:
    workspace, _store, _engine, candidate = _candidate(tmp_path)
    unsafe = candidate.__class__(**{
        **candidate.__dict__,
        "deterministic_checks": (EvolutionCommand(("bash", "-lc", "echo unsafe"), EvolutionCheckKind.DETERMINISTIC, "unsafe"),),
    })
    with pytest.raises(EvolutionWorkspaceError, match="Python interpreter"):
        asyncio.run(LocalEvolutionSandbox(workspace, tmp_path / "sandboxes").evaluate(unsafe))


def test_promoter_blocks_stale_baseline(tmp_path: Path) -> None:
    workspace, _store, _engine, candidate = _candidate(tmp_path)
    (workspace / "calculator.py").write_text("def add(a, b):\n    return 100\n", encoding="utf-8")
    with pytest.raises(EvolutionWorkspaceError, match="baseline changed"):
        asyncio.run(LocalArtifactPromoter(workspace, tmp_path / "backups").promote(candidate))
