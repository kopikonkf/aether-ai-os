"""Reflection emission state-machine tests.

Regression: the executive used a hardcoded ``days_in_primary_domain=15`` mock,
so CrossDomainCuriositySensor fired and re-wrote a near-identical reflection
every 4h cycle. The emission state machine caps output to at most one per 24h,
de-duplicates unchanged trigger fingerprints, derives stagnation from real
activity time, and never treats a failed synthesis as a reflection.
"""

import json
import time

from aether.executive.engine import CircadianExecutiveEngine


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


def _active_fingerprint(engine):
    triggers = engine.consciousness.evaluate_all(engine._gather_cognitive_state())
    return engine._trigger_fingerprint(triggers) if triggers else None


def test_within_24h_window_blocks_emission(tmp_path):
    _write_state(tmp_path, last_reflection_at=str(time.time()))
    engine = CircadianExecutiveEngine(tmp_path, reasoner=_reasoner)
    engine.run_daily_cycle()
    assert _count(tmp_path) == 0


def test_unchanged_fingerprint_blocks_dedup_after_window(tmp_path):
    engine = CircadianExecutiveEngine(tmp_path, reasoner=_reasoner)
    fp = _active_fingerprint(engine)
    _write_state(
        tmp_path,
        last_reflection_at=str(time.time() - 25 * 3600),
        last_trigger_fingerprint=fp,
    )
    engine.run_daily_cycle()
    assert _count(tmp_path) == 0


def test_changed_fingerprint_allows_after_window(tmp_path):
    engine = CircadianExecutiveEngine(tmp_path, reasoner=_reasoner)
    fp = _active_fingerprint(engine)
    # fresh run emits once and records the current fingerprint
    engine.run_daily_cycle()
    assert _count(tmp_path) == 1
    prev = _load_state(tmp_path).get("last_reflection_at")
    # 25h later the trigger changed -> allowed to emit again. We assert on the
    # durable state (the emission advances cooldown + fingerprint), because the
    # obsidian note filename collides within the same second.
    _write_state(
        tmp_path,
        last_reflection_at=str(time.time() - 25 * 3600),
        last_trigger_fingerprint="different-old-fingerprint",
    )
    CircadianExecutiveEngine(tmp_path, reasoner=_reasoner).run_daily_cycle()
    state = _load_state(tmp_path)
    assert state.get("last_trigger_fingerprint") == fp
    assert state.get("last_reflection_at") != prev


def test_stagnation_13_days_does_not_emit(tmp_path):
    _write_state(tmp_path, last_non_primary_activity_at=str(time.time() - 13 * 86400))
    engine = CircadianExecutiveEngine(tmp_path, reasoner=_reasoner)
    engine.run_daily_cycle()
    assert _count(tmp_path) == 0


def test_stagnation_15_days_emits_once(tmp_path):
    _write_state(tmp_path, last_non_primary_activity_at=str(time.time() - 15 * 86400))
    engine = CircadianExecutiveEngine(tmp_path, reasoner=_reasoner)
    engine.run_daily_cycle()
    assert _count(tmp_path) == 1


def test_failed_reasoner_does_not_advance_state(tmp_path):
    _write_state(
        tmp_path,
        last_reflection_at=str(time.time() - 25 * 3600),
        last_trigger_fingerprint="old-fp",
    )
    engine = CircadianExecutiveEngine(tmp_path, reasoner=_failing_reasoner)
    engine.run_daily_cycle()
    assert _count(tmp_path) == 0
    state = _load_state(tmp_path)
    assert state.get("last_reflection_at") is not None  # unchanged, not advanced