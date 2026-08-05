"""Tests for the CircadianExecutiveEngine reflection loop.

Regression: the executive used a hardcoded ``days_in_primary_domain: 15``
mock, so the CrossDomainCuriositySensor fired and wrote a near-identical
04_Reflections note every 4-hour cycle. These tests lock in the fix that
(a) measures domain stagnation from real state and (b) applies a cooldown.
"""

import json
import time

from aether.executive.engine import CircadianExecutiveEngine


def _fake_reasoner(prompt: str) -> str:
    return "Synthesized epiphany for tests."


def _reflection_dir(tmp_path):
    return tmp_path / "obsidian" / "vault" / "04_Reflections"


def _count(tmp_path):
    folder = _reflection_dir(tmp_path)
    if not folder.exists():
        return 0
    return len(list(folder.glob("*.md")))


def _make_engine(tmp_path):
    return CircadianExecutiveEngine(tmp_path, reasoner=_fake_reasoner)


def _state(engine):
    return json.loads(engine._state_path().read_text("utf-8"))


def test_first_run_writes_one_reflection_and_records_state(tmp_path):
    engine = _make_engine(tmp_path)
    engine.run_daily_cycle()
    assert _count(tmp_path) == 1
    assert _state(engine).get("last_cross_domain_reflection_at") is not None


def test_second_cycle_within_cooldown_is_quiet(tmp_path):
    engine = _make_engine(tmp_path)
    engine.run_daily_cycle()   # writes 1 reflection, records timestamp
    engine.run_daily_cycle()   # days since last = 0 -> sensor quiet
    assert _count(tmp_path) == 1


def test_explicit_trigger_reflection_emits_once(tmp_path):
    engine = _make_engine(tmp_path)
    triggers = [
        {"sensor_name": "CrossDomainCuriositySensor",
         "context": "Cross-domain stagnation message."},
    ]
    engine.trigger_reflection(triggers)
    engine.trigger_reflection(triggers)
    engine.trigger_reflection(triggers)
    assert _count(tmp_path) == 1


def test_days_since_negative_or_invalid_is_zero(tmp_path):
    engine = _make_engine(tmp_path)
    assert engine._days_since(str(time.time() + 99999)) == 0
    assert engine._days_since(None) == 0
    assert engine._days_since("nan") == 0