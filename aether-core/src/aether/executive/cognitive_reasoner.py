"""CognitiveReasoner — bounded UNDERSTAND layer for the Aether Cognitive Executive.

Gate 4 closed-loop proof (MISSION-PCP-003 WORK-2): the understand step takes a
CognitiveObservation (WORK-1) and produces a CognitiveDirective — bounded,
fail-closed, never dispatched. The default RuleBasedReasoner is fully
deterministic (no LLM, no randomness) and BoundedDirectiveGuard enforces
hard bounds on every directive so the Cognitive Executive loop can never emit
an unbounded plan.

Purely functional (NON-ACTIVATION): a reasoner only reads an observation and
returns a directive; it never reads stores, never writes, never talks to Herdr.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, Protocol

from aether.executive.cognitive_observer import CognitiveObservation

# Hard bounds enforced by BoundedDirectiveGuard / enforce_bounds.
MAX_STEPS = 5
MAX_BUDGET = 10.0

# Required string fields: an empty one is a hard failure, never clamped.
_REQUIRED_FIELDS = (
    "objective",
    "expected_artifact",
    "principal_id",
    "execution_profile",
    "workspace_id",
)


class InvalidDirectiveError(ValueError):
    """Raised when a directive is missing a required field (fail-closed)."""


@dataclass(frozen=True)
class CognitiveDirective:
    """Bounded, governance-traceable instruction for one cognitive step."""

    objective: str
    expected_artifact: str
    principal_id: str
    execution_profile: str
    workspace_id: str
    capabilities: tuple[str, ...] = ()
    max_steps: int = 1
    budget_usd: float = 10.0
    stop_conditions: tuple[str, ...] = ()
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serializable form for evidence / traceability."""
        return {
            "objective": self.objective,
            "expected_artifact": self.expected_artifact,
            "principal_id": self.principal_id,
            "execution_profile": self.execution_profile,
            "workspace_id": self.workspace_id,
            "capabilities": list(self.capabilities),
            "max_steps": self.max_steps,
            "budget_usd": self.budget_usd,
            "stop_conditions": list(self.stop_conditions),
            "rationale": self.rationale,
        }

    def validate(self) -> list[str]:
        """Return blockers; empty list means the directive is valid.

        workspace_id is intentionally NOT a directive-level blocker: the
        rule-based reasoner legitimately emits an empty workspace and leaves a
        concrete binding to the planner/executor. A concrete workspace is only
        enforced at the execution boundary (enforce_bounds), never here.
        """
        blockers: list[str] = []
        if not self.objective:
            blockers.append("objective")
        if not self.expected_artifact:
            blockers.append("expected_artifact")
        if not self.principal_id:
            blockers.append("principal_id")
        if not self.execution_profile:
            blockers.append("execution_profile")
        if self.max_steps < 1:
            blockers.append("max_steps")
        if self.budget_usd < 0:
            blockers.append("budget_usd")
        return blockers


class CognitiveReasoner(Protocol):
    """Injectable understand step: observation -> bounded directive."""

    def reason(self, observation: CognitiveObservation) -> CognitiveDirective: ...


class RuleBasedReasoner:
    """Deterministic default reasoner (rule-based, no model, no dispatch)."""

    _DEFAULT_CAPABILITIES = ("systems_integration",)
    _DEFAULT_STOP_CONDITIONS = ("stop when budget exhausted",)

    def __init__(
        self,
        workspace_override: str | None = None,
        principal_id: str = "chatgpt",
        execution_profile: str = "herdr:opencode",
        expected_artifact: str = "WORK-PCP-003.md",
    ) -> None:
        self._workspace_override = workspace_override
        self._principal_id = principal_id
        self._execution_profile = execution_profile
        self._expected_artifact = expected_artifact

    def reason(self, observation: CognitiveObservation) -> CognitiveDirective:
        summary = observation.summary or ""
        return CognitiveDirective(
            objective=f"Address observed Aether state: {summary}",
            expected_artifact=self._expected_artifact,
            principal_id=self._principal_id,
            execution_profile=self._execution_profile,
            workspace_id=self._workspace_override or "",
            capabilities=self._DEFAULT_CAPABILITIES,
            max_steps=1,
            budget_usd=10.0,
            stop_conditions=self._DEFAULT_STOP_CONDITIONS,
            rationale="rule-based: deterministic default",
        )


def enforce_bounds(directive: CognitiveDirective) -> CognitiveDirective:
    """Fail-closed bounds enforcement: clamp numerics, raise on missing requireds.

    Documented rule (chosen pattern: clamp + required-field raise):
      - A missing required field (objective / expected_artifact / principal_id /
        execution_profile / workspace_id) raises InvalidDirectiveError — never
        emit a partially-unsafe directive.
      - max_steps is clamped to [1, MAX_STEPS].
      - budget_usd is clamped to [0, MAX_BUDGET].
      - capabilities and stop_conditions pass through untouched.
    """
    missing = [
        blocker
        for blocker in directive.validate()
        if blocker in _REQUIRED_FIELDS
    ]
    if missing:
        raise InvalidDirectiveError(
            "directive missing required fields: " + ", ".join(sorted(missing))
        )
    return dataclasses.replace(
        directive,
        max_steps=max(1, min(MAX_STEPS, directive.max_steps)),
        budget_usd=max(0.0, min(MAX_BUDGET, directive.budget_usd)),
    )


class BoundedDirectiveGuard:
    """Wrapper that bounds any CognitiveReasoner's output fail-closed."""

    def __init__(self, reasoner: CognitiveReasoner) -> None:
        self._reasoner = reasoner

    def reason(self, observation: CognitiveObservation) -> CognitiveDirective:
        return enforce_bounds(self._reasoner.reason(observation))


def guard(reasoner: CognitiveReasoner) -> BoundedDirectiveGuard:
    """Wrap a reasoner so every emitted directive is bounded fail-closed."""
    return BoundedDirectiveGuard(reasoner)
