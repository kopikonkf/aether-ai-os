"""MISSION-PCP-003 WORK-2 — CognitiveReasoner bounded directive tests.

Tests for aether.executive.cognitive_reasoner:
  - RuleBasedReasoner returns a valid directive whose objective mentions "state";
  - workspace_override is honoured by the rule-based reasoner;
  - CognitiveDirective.validate() rejects empty/mis-bounded fields;
  - to_dict() round-trips the core fields;
  - enforce_bounds clamps max_steps/budget_usd and raises on a missing required
    field (fail-closed);
  - the CognitiveReasoner Protocol accepts a stub implementation.

Deterministic: pure functions, no network, no live herdr.
"""
from __future__ import annotations

from typing import cast

from aether.executive.cognitive_observer import CognitiveObservation
from aether.executive.cognitive_reasoner import (
    MAX_BUDGET,
    MAX_STEPS,
    BoundedDirectiveGuard,
    CognitiveDirective,
    CognitiveReasoner,
    CognitiveStepSpec,
    InvalidDirectiveError,
    RuleBasedReasoner,
    enforce_bounds,
    guard,
)


def empty_observation() -> CognitiveObservation:
    return CognitiveObservation(observed_at="2026-08-13T00:00:00Z")


def valid_directive(**overrides) -> CognitiveDirective:
    fields = {
        "objective": "Address observed Aether state",
        "expected_artifact": "WORK-PCP-003.md",
        "principal_id": "chatgpt",
        "execution_profile": "herdr:opencode",
        "workspace_id": "workspace://default",
        "max_steps": 1,
        "budget_usd": 10.0,
    }
    fields.update(overrides)
    return CognitiveDirective(**fields)


def test_rule_based_reasoner_returns_valid_directive():
    directive = RuleBasedReasoner().reason(empty_observation())
    assert directive.validate() == []
    assert "state" in directive.objective
    assert directive.expected_artifact == "WORK-PCP-003.md"
    assert directive.principal_id == "chatgpt"
    assert directive.execution_profile == "herdr:opencode"


def test_rule_based_reasoner_uses_override():
    reasoner = RuleBasedReasoner(workspace_override="workspace://pcp-003")
    directive = reasoner.reason(empty_observation())
    assert directive.workspace_id == "workspace://pcp-003"
    assert directive.validate() == []


def test_directive_validate_rejects_invalid():
    assert valid_directive(objective="").validate() != []
    assert valid_directive(max_steps=0).validate() != []
    assert valid_directive(budget_usd=-1).validate() != []


def test_directive_to_dict_roundtrip():
    data = valid_directive().to_dict()
    for key in (
        "objective",
        "expected_artifact",
        "principal_id",
        "execution_profile",
        "workspace_id",
        "max_steps",
        "budget_usd",
    ):
        assert key in data
    assert data["max_steps"] == 1
    assert data["budget_usd"] == 10.0


def test_enforce_bounds_clamps():
    bounded = enforce_bounds(valid_directive(max_steps=999, budget_usd=-1))
    assert bounded.max_steps == MAX_STEPS
    assert bounded.budget_usd == 0.0


def test_enforce_bounds_raises_on_missing_objective():
    try:
        enforce_bounds(valid_directive(objective=""))
    except InvalidDirectiveError:
        return
    raise AssertionError("expected InvalidDirectiveError for empty objective")


class _StubReasoner:
    def reason(self, observation: CognitiveObservation) -> CognitiveDirective:
        return valid_directive()


def test_reasoner_protocol_shape():
    reasoner: CognitiveReasoner = _StubReasoner()
    directive = reasoner.reason(empty_observation())
    assert directive.validate() == []
    guarded = cast(BoundedDirectiveGuard, guard(reasoner))
    assert guarded.reason(empty_observation()).validate() == []


# ---------------------------------------------------------------------------
# MISSION-PCP-004 WORK-1 — multi-step directive (Gate 5 acceptance item 1)
# ---------------------------------------------------------------------------
def test_rule_based_reasoner_multi_step_emits_plan_spec():
    directive = RuleBasedReasoner(
        workspace_override="workspace://pcp-004",
        plan_steps=3,
        work_prefix="WORK-PCP-004",
    ).reason(empty_observation())
    assert directive.validate() == []
    assert len(directive.steps) == 3
    assert directive.max_steps == 3
    step_ids = [spec.step_id for spec in directive.steps]
    assert step_ids == ["step-1", "step-2", "step-3"]
    assert directive.steps[1].depends_on == ("step-1",)
    assert directive.steps[2].depends_on == ("step-2",)
    assert directive.steps[0].work_id == "WORK-PCP-004-S1"
    assert directive.steps[0].expected_artifact == "WORK-PCP-004-S1.md"
    assert directive.steps[2].work_id == "WORK-PCP-004-S3"
    assert directive.steps[2].expected_artifact == "WORK-PCP-004-S3.md"


def test_rule_based_reasoner_single_step_legacy_no_steps():
    directive = RuleBasedReasoner().reason(empty_observation())
    assert directive.steps == ()
    assert directive.max_steps == 1
    assert directive.expected_artifact == "WORK-PCP-003.md"


def test_multi_step_directive_validate_rejects_bad_deps():
    directive = CognitiveDirective(
        objective="multi",
        expected_artifact="WORK-PCP-004.md",
        principal_id="chatgpt",
        execution_profile="herdr:opencode",
        workspace_id="workspace://default",
        max_steps=2,
        steps=(
            CognitiveStepSpec("step-1", "WORK-PCP-004-S1", "s1", "WORK-PCP-004-S1.md", ()),
            CognitiveStepSpec("step-2", "WORK-PCP-004-S2", "s2", "WORK-PCP-004-S2.md", ("step-9",)),
        ),
    )
    assert any("unknown steps" in blocker for blocker in directive.validate())


def test_multi_step_directive_validate_rejects_self_dep():
    directive = CognitiveDirective(
        objective="multi",
        expected_artifact="WORK-PCP-004.md",
        principal_id="chatgpt",
        execution_profile="herdr:opencode",
        workspace_id="workspace://default",
        max_steps=2,
        steps=(
            CognitiveStepSpec("step-1", "WORK-PCP-004-S1", "s1", "WORK-PCP-004-S1.md", ("step-1",)),
        ),
    )
    assert any("itself" in blocker for blocker in directive.validate())


def test_multi_step_directive_validate_rejects_low_bound():
    directive = CognitiveDirective(
        objective="multi",
        expected_artifact="WORK-PCP-004.md",
        principal_id="chatgpt",
        execution_profile="herdr:opencode",
        workspace_id="workspace://default",
        max_steps=1,
        steps=(
            CognitiveStepSpec("step-1", "WORK-PCP-004-S1", "s1", "WORK-PCP-004-S1.md", ()),
            CognitiveStepSpec("step-2", "WORK-PCP-004-S2", "s2", "WORK-PCP-004-S2.md", ("step-1",)),
        ),
    )
    assert any("below step count" in blocker for blocker in directive.validate())


def test_multi_step_directive_to_dict_roundtrip():
    directive = valid_directive(
        max_steps=2,
        steps=(
            CognitiveStepSpec("step-1", "WORK-PCP-004-S1", "s1", "WORK-PCP-004-S1.md", ()),
            CognitiveStepSpec("step-2", "WORK-PCP-004-S2", "s2", "WORK-PCP-004-S2.md", ("step-1",)),
        ),
    )
    data = directive.to_dict()
    assert len(data["steps"]) == 2
    assert data["steps"][1]["depends_on"] == ["step-1"]


def test_enforce_bounds_clamps_multi_step_bound_to_step_count():
    bounded = enforce_bounds(
        valid_directive(
            max_steps=1,
            steps=(
                CognitiveStepSpec("step-1", "WORK-PCP-004-S1", "s1", "WORK-PCP-004-S1.md", ()),
                CognitiveStepSpec("step-2", "WORK-PCP-004-S2", "s2", "WORK-PCP-004-S2.md", ("step-1",)),
            ),
        )
    )
    assert bounded.max_steps == 2


def test_enforce_bounds_rejects_too_many_steps():
    too_many = valid_directive(
        max_steps=MAX_STEPS + 1,
        steps=tuple(
            CognitiveStepSpec(
                f"step-{i}",
                f"WORK-PCP-004-S{i}",
                f"s{i}",
                f"WORK-PCP-004-S{i}.md",
                (f"step-{i - 1}",) if i > 1 else (),
            )
            for i in range(1, MAX_STEPS + 2)
        ),
    )
    try:
        enforce_bounds(too_many)
    except InvalidDirectiveError:
        return
    raise AssertionError("expected InvalidDirectiveError for too many steps")


# --- PCP-005 WORK-1 additions (per-step principal directive) ---
# PCP-005 WORK-1 additions (per-step principal directive)
from types import SimpleNamespace

import pytest

from aether.executive.cognitive_observer import CognitiveObservation
from aether.executive.cognitive_reasoner import (
    CognitiveDirective,
    CognitiveStepSpec,
    RuleBasedReasoner,
    _DEFAULT_PROFILE_BY_PRINCIPAL,
    _DEFAULT_STEP_PRINCIPALS,
)


class _FakeRegistry:
    """Duck-typed PrincipalRuntimeProfiles stand-in (no real YAML in unit tests)."""

    def __init__(self, entries):
        self._entries = entries

    def get_principal(self, pid):
        return self._entries.get(pid)


def _observe(summary="state snapshot"):
    return CognitiveObservation(observed_at="2026-08-13T00:00:00Z", summary=summary)


def _registry():
    """Minimal fake mirroring principal_runtime_profiles.v0.yaml principals."""
    return _FakeRegistry(
        {
            "chatgpt": SimpleNamespace(model_provider="openai", execution_profiles=("herdr:opencode",)),
            "claude": SimpleNamespace(model_provider="anthropic", execution_profiles=("herdr:freebuff",)),
            "gemini": SimpleNamespace(model_provider="google", execution_profiles=("herdr:claude",)),
            "qwen": SimpleNamespace(model_provider="alibaba", execution_profiles=("herdr:cline",)),
            "deepseek": SimpleNamespace(model_provider="deepseek", execution_profiles=("herdr:kilo",)),
            "kimi": SimpleNamespace(model_provider="moonshot", execution_profiles=("herdr:kimi",)),
            "opencode": SimpleNamespace(model_provider="opencode", execution_profiles=("herdr:opencode",)),
        }
    )


def test_multi_principal_steps_distinct():
    reasoner = RuleBasedReasoner(
        plan_steps=5, step_principals=_DEFAULT_STEP_PRINCIPALS, work_prefix="WORK-PCP-005"
    )
    directive = reasoner.reason(_observe())
    assert len(directive.steps) == 5
    principals = tuple(spec.principal_id for spec in directive.steps)
    assert principals == _DEFAULT_STEP_PRINCIPALS  # (claude, gemini, qwen, deepseek, chatgpt)
    assert len(set(principals)) == 5
    assert directive.require_distinct_principals is True
    assert directive.validate() == []


def test_legacy_steps_inherit_directive_principal():
    reasoner = RuleBasedReasoner(plan_steps=3, principal_id="chatgpt", execution_profile="herdr:opencode")
    directive = reasoner.reason(_observe())
    assert len(directive.steps) == 3
    assert directive.require_distinct_principals is False
    assert all(spec.principal_id is None for spec in directive.steps)
    assert all(spec.execution_profile is None for spec in directive.steps)
    assert directive.validate() == []  # backward compat


def test_step_principals_length_mismatch_raises():
    with pytest.raises(ValueError):
        RuleBasedReasoner(plan_steps=3, step_principals=("claude", "gemini"))


def test_validate_rejects_unregistered_principal_with_profiles():
    directive = CognitiveDirective(
        objective="o",
        expected_artifact="a",
        principal_id="chatgpt",
        execution_profile="herdr:opencode",
        workspace_id="w",
        max_steps=1,
        steps=(
            CognitiveStepSpec(
                step_id="s1", work_id="w1", objective="o", expected_artifact="a",
                principal_id="ghost",
            ),
        ),
    )
    blockers = directive.validate(profiles=_registry())
    assert "step s1 principal ghost not registered" in blockers


def test_validate_rejects_conflated_principal_with_profiles():
    directive = CognitiveDirective(
        objective="o",
        expected_artifact="a",
        principal_id="chatgpt",
        execution_profile="herdr:opencode",
        workspace_id="w",
        max_steps=1,
        steps=(
            CognitiveStepSpec(
                step_id="s1", work_id="w1", objective="o", expected_artifact="a",
                principal_id="opencode", execution_profile="herdr:opencode",
            ),
        ),
    )
    blockers = directive.validate(profiles=_registry())
    assert "step s1 principal/model_provider conflated" in blockers


def test_validate_rejects_duplicate_principal_when_required():
    directive = CognitiveDirective(
        objective="o",
        expected_artifact="a",
        principal_id="chatgpt",
        execution_profile="herdr:opencode",
        workspace_id="w",
        max_steps=2,
        require_distinct_principals=True,
        steps=(
            CognitiveStepSpec(step_id="s1", work_id="w1", objective="o", expected_artifact="a", principal_id="claude"),
            CognitiveStepSpec(step_id="s2", work_id="w2", objective="o", expected_artifact="a", principal_id="claude"),
        ),
    )
    blockers = directive.validate()
    assert "duplicate principal across steps: claude" in blockers


def test_to_dict_round_trip_includes_per_step_principal():
    reasoner = RuleBasedReasoner(
        plan_steps=2, step_principals=("claude", "gemini"), work_prefix="WORK-PCP-005"
    )
    data = reasoner.reason(_observe()).to_dict()
    assert data["require_distinct_principals"] is True
    assert data["steps"][0]["principal_id"] == "claude"
    assert data["steps"][0]["execution_profile"] == _DEFAULT_PROFILE_BY_PRINCIPAL["claude"]
    assert data["steps"][1]["principal_id"] == "gemini"
    assert data["steps"][1]["execution_profile"] == _DEFAULT_PROFILE_BY_PRINCIPAL["gemini"]
