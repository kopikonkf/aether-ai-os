"""CognitiveReasoner — bounded UNDERSTAND layer for the Aether Cognitive Executive.

Gate 4 closed-loop proof (MISSION-PCP-003 WORK-2): the understand step takes a
CognitiveObservation (WORK-1) and produces a CognitiveDirective — bounded,
fail-closed, never dispatched. The default RuleBasedReasoner is fully
deterministic (no LLM, no randomness) and BoundedDirectiveGuard enforces
hard bounds on every directive so the Cognitive Executive loop can never emit
an unbounded plan.

Gate 6 (MISSION-PCP-005 WORK-1): CognitiveStepSpec carries an OPTIONAL per-step
principal_id / execution_profile so a reasoner can assign a DIFFERENT principal
per step (multi-principal planning). CognitiveDirective.validate() optionally
accepts a PrincipalRuntimeProfiles-like registry and enforces that every
per-step effective principal is registered, distinct from its execution profile,
and not conflated with its model provider — all fail-closed.

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

# Multi-principal default order used by RuleBasedReasoner step_principals mode.
_DEFAULT_STEP_PRINCIPALS = ("claude", "gemini", "qwen", "deepseek", "chatgpt")

# Principal -> execution profile used when assigning a DIFFERENT principal per
# step. A principal without a mapped profile keeps execution_profile=None and
# lets the planner derive a concrete binding.
_DEFAULT_PROFILE_BY_PRINCIPAL = {
    "claude": "herdr:freebuff",
    "gemini": "herdr:claude",
    "qwen": "herdr:cline",
    "deepseek": "herdr:kilo",
    "chatgpt": "herdr:opencode",
}


class InvalidDirectiveError(ValueError):
    """Raised when a directive is missing a required field (fail-closed)."""


@dataclass(frozen=True)
class CognitiveStepSpec:
    """Bounded, governance-traceable description of ONE plan step.

    A multi-step directive (MISSION-PCP-004) carries a tuple of these specs;
    the planner turns each spec into a canonical MissionStep with its own
    work_id / expected_artifact / depends_on, and links step N+1 to step N via
    `relevant_artifacts` so the deliverable of step N becomes the evidence /
    input context for step N+1 (Gate 5 acceptance item 3).

    Gate 6 (PCP-005): a step MAY override the directive-level principal /
    execution profile with optional per-step `principal_id` / `execution_profile`.
    When either is None the step inherits the directive-level value.
    """

    step_id: str
    work_id: str
    objective: str
    expected_artifact: str
    depends_on: tuple[str, ...] = ()
    acceptance: tuple[str, ...] = ()
    principal_id: str | None = None
    execution_profile: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "work_id": self.work_id,
            "objective": self.objective,
            "expected_artifact": self.expected_artifact,
            "depends_on": list(self.depends_on),
            "acceptance": list(self.acceptance),
            "principal_id": self.principal_id,
            "execution_profile": self.execution_profile,
        }


@dataclass(frozen=True)
class CognitiveDirective:
    """Bounded, governance-traceable instruction for one cognitive mission.

    Single-step (legacy, PCP-003): objective + expected_artifact describe one
    step and `steps` stays empty. Multi-step (PCP-004): `steps` carries the
    bounded plan decomposition; the top-level objective/expected_artifact remain
    the mission-level fallback the planner uses when `steps` is empty.

    Gate 6 (PCP-005): per-step principal governance is enabled via the new
    `require_distinct_principals` flag and the optional `profiles` argument of
    validate().
    """

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
    steps: tuple[CognitiveStepSpec, ...] = ()
    require_distinct_principals: bool = False

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
            "steps": [spec.to_dict() for spec in self.steps],
            "require_distinct_principals": self.require_distinct_principals,
        }

    def validate(self, profiles=None) -> list[str]:
        """Return blockers; empty list means the directive is valid.

        workspace_id is intentionally NOT a directive-level blocker: the
        rule-based reasoner legitimately emits an empty workspace and leaves a
        concrete binding to the planner/executor. A concrete workspace is only
        enforced at the execution boundary (enforce_bounds), never here.

        When `steps` is non-empty (multi-step), every step spec must be
        well-formed: unique step_ids, work_id/objective/expected_artifact set,
        depends_on referencing known steps, no self-dependency, bounded to
        MAX_STEPS, and max_steps must cover the step count (the loop bound is
        min(executive.max_steps, directive.max_steps), so a plan with N steps
        needs max_steps >= N to reach completion).

        Gate 6 (PCP-005): per-step principal governance. `profiles` is an
        optional PrincipalRuntimeProfiles-like object exposing `get_principal(id)`
        that returns an object with `.model_provider` and `.execution_profiles`
        (None = structural-only legacy mode). For every step the EFFECTIVE
        principal/profile are `spec.X or self.X`. New fail-closed blockers are
        appended AFTER the existing checks, so calling validate() with no
        arguments behaves exactly as before for legacy directives.
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
        if self.steps:
            ids = [spec.step_id for spec in self.steps]
            if len(ids) != len(set(ids)):
                blockers.append("step ids must be unique")
            if len(self.steps) > MAX_STEPS:
                blockers.append(f"steps exceed MAX_STEPS={MAX_STEPS}")
            known = set(ids)
            for spec in self.steps:
                if not spec.step_id or not spec.work_id or not spec.objective or not spec.expected_artifact:
                    blockers.append(
                        f"step {spec.step_id or '?'} incomplete (step_id/work_id/objective/expected_artifact)"
                    )
                    continue
                missing = set(spec.depends_on) - known
                if missing:
                    blockers.append(
                        f"step {spec.step_id} depends on unknown steps: {', '.join(sorted(missing))}"
                    )
                if spec.step_id in spec.depends_on:
                    blockers.append(f"step {spec.step_id} cannot depend on itself")
            if self.max_steps < len(self.steps):
                blockers.append(f"max_steps {self.max_steps} below step count {len(self.steps)}")

            # -- Gate 6 per-step principal governance (fail-closed) ----------
            effective_principals: list[str] = []
            for spec in self.steps:
                step_label = spec.step_id or "?"
                principal = spec.principal_id or self.principal_id
                profile = spec.execution_profile or self.execution_profile
                if not principal:
                    blockers.append(f"step {step_label} empty effective principal")
                    continue
                effective_principals.append(principal)
                if principal == profile:
                    blockers.append(f"step {step_label} principal equals execution_profile")
                if profiles is not None:
                    registered = profiles.get_principal(principal)
                    if registered is None:
                        blockers.append(f"step {step_label} principal {principal} not registered")
                    else:
                        model_provider = getattr(registered, "model_provider", None)
                        if model_provider == principal or model_provider == profile:
                            blockers.append(f"step {step_label} principal/model_provider conflated")
                        # R-PCP005-1 (WORK-4): a per-step execution_profile must be
                        # one the principal is actually registered with. An explicit
                        # profile that belongs to a DIFFERENT principal is a blocker
                        # (fail-closed), never silently remapped at dispatch.
                        if (
                            spec.execution_profile
                            and profile
                            and profile not in getattr(registered, "execution_profiles", ())
                        ):
                            blockers.append(
                                f"step {step_label} profile {profile} not registered to principal {principal}"
                            )
            if self.require_distinct_principals:
                seen: set[str] = set()
                for principal in effective_principals:
                    if principal in seen:
                        blockers.append(f"duplicate principal across steps: {principal}")
                        break
                    seen.add(principal)
        return blockers


class CognitiveReasoner(Protocol):
    """Injectable understand step: observation -> bounded directive."""

    def reason(self, observation: CognitiveObservation) -> CognitiveDirective: ...


class RuleBasedReasoner:
    """Deterministic default reasoner (rule-based, no model, no dispatch).

    Single-step (legacy): emits a directive whose single expected artifact is
    `expected_artifact`. Multi-step (PCP-004): when `plan_steps` > 1 the reasoner
    deterministically decomposes the mission into `plan_steps` chained steps —
    each with its own work_id (``<work_prefix>-S{n}``), expected artifact
    (``<work_prefix>-S{n}.md``) and a linear depends_on chain, so the planner can
    build a bounded multi-step plan and the executive can chain artifacts step
    N -> step N+1.

    Gate 6 (PCP-005): passing `step_principals` assigns a DIFFERENT principal
    per step (plus a mapped execution_profile when known) and flips
    require_distinct_principals on the emitted directive. When `step_principals`
    is empty the behavior is EXACTLY legacy (all steps inherit the directive
    principal/profile, require_distinct_principals=False).
    """

    _DEFAULT_CAPABILITIES = ("systems_integration",)
    _DEFAULT_STOP_CONDITIONS = ("stop when budget exhausted",)

    def __init__(
        self,
        workspace_override: str | None = None,
        principal_id: str = "chatgpt",
        execution_profile: str = "herdr:opencode",
        expected_artifact: str = "WORK-PCP-003.md",
        plan_steps: int = 1,
        work_prefix: str = "WORK-PCP-003",
        step_principals: tuple[str, ...] = (),
    ) -> None:
        self._workspace_override = workspace_override
        self._principal_id = principal_id
        self._execution_profile = execution_profile
        self._expected_artifact = expected_artifact
        self._plan_steps = max(1, int(plan_steps))
        self._work_prefix = work_prefix
        if step_principals and len(step_principals) != self._plan_steps:
            raise ValueError(
                f"step_principals length {len(step_principals)} must equal plan_steps {self._plan_steps}"
            )
        self._step_principals = step_principals

    def reason(self, observation: CognitiveObservation) -> CognitiveDirective:
        summary = observation.summary or ""
        base = dict(
            objective=f"Address observed Aether state: {summary}",
            principal_id=self._principal_id,
            execution_profile=self._execution_profile,
            workspace_id=self._workspace_override or "",
            capabilities=self._DEFAULT_CAPABILITIES,
            budget_usd=10.0,
            stop_conditions=self._DEFAULT_STOP_CONDITIONS,
            rationale="rule-based: deterministic default",
            require_distinct_principals=bool(self._step_principals),
        )
        if self._plan_steps <= 1:
            return CognitiveDirective(
                expected_artifact=self._expected_artifact,
                max_steps=1,
                **base,
            )
        steps: list[CognitiveStepSpec] = []
        for index in range(1, self._plan_steps + 1):
            work_id = f"{self._work_prefix}-S{index}"
            artifact = f"{work_id}.md"
            depends_on = (f"step-{index - 1}",) if index > 1 else ()
            acceptance = (
                f"produce {artifact}",
                f"step {index - 1} artifact is input context"
                if index > 1
                else "first step needs no input artifact",
            )
            step_principal = self._step_principals[index - 1] if self._step_principals else None
            steps.append(
                CognitiveStepSpec(
                    step_id=f"step-{index}",
                    work_id=work_id,
                    objective=f"Deliver {artifact} as step {index} of {self._plan_steps}.",
                    expected_artifact=artifact,
                    depends_on=depends_on,
                    acceptance=acceptance,
                    principal_id=step_principal,
                    execution_profile=(
                        _DEFAULT_PROFILE_BY_PRINCIPAL.get(step_principal) if step_principal else None
                    ),
                )
            )
        return CognitiveDirective(
            expected_artifact=self._expected_artifact,
            max_steps=len(steps),
            steps=tuple(steps),
            **base,
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
    clamped_steps = directive.steps
    if len(clamped_steps) > MAX_STEPS:
        raise InvalidDirectiveError(
            f"directive exceeds MAX_STEPS={MAX_STEPS}: {len(clamped_steps)} steps"
        )
    if clamped_steps:
        max_steps = max(1, min(MAX_STEPS, max(directive.max_steps, len(clamped_steps))))
    else:
        max_steps = max(1, min(MAX_STEPS, directive.max_steps))
    return dataclasses.replace(
        directive,
        max_steps=max_steps,
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
