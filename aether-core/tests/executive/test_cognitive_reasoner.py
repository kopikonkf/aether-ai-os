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
