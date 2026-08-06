"""Reflection emission state-machine tests (deterministic clock).

Covers: emission window (<24h / exactly 24h / >24h), new-trigger and
severity-increase emission rules, non-triggering unavailable activity signal,
atomic persistence failure propagation, and full-state preservation when the
reasoner fails.
"""

import json
import time

import pytest

from aether.executive.engine import CircadianExecutiveEngine, REFLECTION_EMIT_WINDOW_SECONDS

T = 1_800_000_000.0  # fixed "now" for the deterministic clock


def _write_state(root, **kv):
    p = root / "runtime_state" / "reflection_state.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(kv), encoding="utf-8")


def _load_state(root):
    p = root / "runtime_state" / "reflection_state.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def _count(root):
    folder = root / "obsidian" / "vault" / "04_Reflections"
    if not folder.exists():
        return 0
    return len(list(folder.glob("*.md")))


def _reasoner(prompt: str) -> str:
    return "synthesized epiphany"


def _failing_reasoner(prompt: str) -> str:
    raise RuntimeError("reasoning backend down")


def _engine(root, reasoner=_reasoner):
    return CircadianExecutiveEngine(root, reasoner=reasoner, clock=lambda: T)


def _active(engine):
    triggers = engine.consciousness.evaluate_all(engine._gather_cognitive_state())
    return triggers, engine._trigger_fingerprint(triggers), engine._max_severity(triggers)


def test_missing_activity_signal_is_non_triggering(tmp_path):
    engine = _engine(tmp_path)  # no state at all -> signal unavailable
    engine.run_daily_cycle()
    assert _count(tmp_path) == 0
    assert not (tmp_path / "runtime_state" / "reflection_state.json").exists()


def test_within_24h_window_blocks_emission(tmp_path):
    _write_state(
        tmp_path,
        last_reflection_at=str(T - 3600),
        last_non_primary_activity_at=str(T - 20 * 86400),
    )
    engine = _engine(tmp_path)
    engine.run_daily_cycle()
    assert _count(tmp_path) == 0


def test_exact_24h_allows_emission(tmp_path):
    _write_state(
        tmp_path,
        last_reflection_at=str(T - REFLECTION_EMIT_WINDOW_SECONDS),
        last_trigger_fingerprint="old-fp",
        last_non_primary_activity_at=str(T - 20 * 86400),
    )
    engine = _engine(tmp_path)
    engine.run_daily_cycle()
    assert _count(tmp_path) == 1


def test_after_24h_allows_emission(tmp_path):
    _write_state(
        tmp_path,
        last_reflection_at=str(T - 25 * 3600),
        last_trigger_fingerprint="old-fp",
        last_non_primary_activity_at=str(T - 20 * 86400),
    )
    engine = _engine(tmp_path)
    engine.run_daily_cycle()
    assert _count(tmp_path) == 1


def test_unchanged_fingerprint_and_severity_blocks(tmp_path):
    _write_state(tmp_path, last_non_primary_activity_at=str(T - 20 * 86400))
    engine = _engine(tmp_path)
    triggers, fp, sev = _active(engine)
    assert triggers, "cross-domain sensor should fire at 20 days"
    _write_state(
        tmp_path,
        last_reflection_at=str(T - 25 * 3600),
        last_trigger_fingerprint=fp,
        last_trigger_severity=str(sev),
        last_non_primary_activity_at=str(T - 20 * 86400),
    )
    _engine(tmp_path).run_daily_cycle()
    assert _count(tmp_path) == 0


def test_severity_increase_emits(tmp_path):
    _write_state(tmp_path, last_non_primary_activity_at=str(T - 20 * 86400))
    engine = _engine(tmp_path)
    triggers, fp, sev = _active(engine)
    _write_state(
        tmp_path,
        last_reflection_at=str(T - 25 * 3600),
        last_trigger_fingerprint=fp,
        last_trigger_severity=str(sev - 0.3),  # lower severity before -> increase
        last_non_primary_activity_at=str(T - 20 * 86400),
    )
    _engine(tmp_path).run_daily_cycle()
    assert _count(tmp_path) == 1


def test_severity_decrease_does_not_emit(tmp_path):
    _write_state(tmp_path, last_non_primary_activity_at=str(T - 20 * 86400))
    engine = _engine(tmp_path)
    triggers, fp, sev = _active(engine)
    _write_state(
        tmp_path,
        last_reflection_at=str(T - 25 * 3600),
        last_trigger_fingerprint=fp,
        last_trigger_severity=str(sev + 0.3),  # higher severity before -> decrease
        last_non_primary_activity_at=str(T - 20 * 86400),
    )
    _engine(tmp_path).run_daily_cycle()
    assert _count(tmp_path) == 0


def test_failed_reasoner_leaves_state_fully_unchanged(tmp_path):
    before = {
        "last_reflection_at": str(T - 25 * 3600),
        "last_trigger_fingerprint": "fp-before",
        "last_trigger_severity": "0.5",
        "last_non_primary_activity_at": str(T - 20 * 86400),
    }
    _write_state(tmp_path, **before)
    engine = CircadianExecutiveEngine(tmp_path, reasoner=_failing_reasoner, clock=lambda: T)
    engine.run_daily_cycle()
    assert _count(tmp_path) == 0
    assert _load_state(tmp_path) == before


def test_state_persistence_failure_propagates_and_no_note(tmp_path):
    # State is readable (so the sensor can fire) but the atomic save target is
    # blocked: a directory occupies the .tmp path -> open() raises, which must
    # propagate instead of being swallowed as a successful emission.
    _write_state(tmp_path, last_non_primary_activity_at=str(T - 20 * 86400))
    (tmp_path / "runtime_state" / "reflection_state.json.tmp").mkdir()

    engine = _engine(tmp_path)
    with pytest.raises(Exception):
        engine.run_daily_cycle()
    assert _count(tmp_path) == 0
    state = _load_state(tmp_path)
    assert "last_reflection_at" not in state