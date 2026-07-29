"""Provider-neutral contracts for Northstar-bounded missions and external value experiments."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from aether.contracts.actions import ActionProposal, ActionResult, proposal_from_payload, proposal_payload
from aether.utils.ids import new_id


class MissionLane(StrEnum):
    INTERNAL_MAINTENANCE = "internal-maintenance"
    EXTERNAL_VALUE = "external-value"


class OpportunityEvidenceStance(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"


class MissionRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class MissionStatus(StrEnum):
    DRAFT = "draft"
    REVIEW_REQUIRED = "review-required"
    APPROVED = "approved"
    REJECTED = "rejected"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting-approval"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    STOPPED = "stopped"


class MissionStepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting-approval"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class MissionDecisionType(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class MissionValueKind(StrEnum):
    CLAIMED = "claimed"
    REALIZED = "realized"
    VERIFIED = "verified"


class MissionOutcomeState(StrEnum):
    CLAIMED = "claimed"
    REALIZED = "realized"
    VERIFIED = "verified"
    NO_VALUE = "no-value"


@dataclass(frozen=True)
class OpportunityEvidence:
    source: str
    statement: str
    stance: OpportunityEvidenceStance = OpportunityEvidenceStance.SUPPORTS
    observed_at: str = ""
    external_reference: str | None = None
    independent_source_id: str | None = None
    verified: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)
    evidence_id: str = field(default_factory=lambda: new_id("opp-evidence"))
    content_hash: str = ""


@dataclass(frozen=True)
class ExpectedValueBrief:
    title: str
    lane: MissionLane
    problem_statement: str
    beneficiary: str
    value_proposition: str
    probability_success: float
    upside_usd: float
    estimated_cost_usd: float
    estimated_duration_hours: float
    expected_net_value_usd: float
    revenue_hypothesis: str
    assumptions: tuple[str, ...]
    evidence: tuple[OpportunityEvidence, ...]
    contradiction_evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    independent_support_count: int = 0
    risk: MissionRisk = MissionRisk.MEDIUM
    confidence: float = 0.5
    blockers: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    brief_id: str = field(default_factory=lambda: new_id("opp-brief"))
    brief_hash: str = ""
    created_at: str = ""


@dataclass(frozen=True)
class MissionBudget:
    max_cost_usd: float = 10.0
    max_duration_seconds: int = 3600
    max_step_attempts: int = 10
    max_high_risk_actions: int = 0
    minimum_expected_value_usd: float = 0.0

    def validate(self) -> None:
        if self.max_cost_usd < 0:
            raise ValueError("max_cost_usd cannot be negative")
        if self.max_duration_seconds < 1:
            raise ValueError("max_duration_seconds must be positive")
        if self.max_step_attempts < 1:
            raise ValueError("max_step_attempts must be positive")
        if self.max_high_risk_actions < 0:
            raise ValueError("max_high_risk_actions cannot be negative")


@dataclass(frozen=True)
class MissionStep:
    title: str
    action: ActionProposal
    success_criteria: tuple[str, ...]
    depends_on: tuple[str, ...] = field(default_factory=tuple)
    max_attempts: int = 1
    stop_on_failure: bool = True
    explicit_retry_reason: str | None = None
    estimated_cost_usd: float = 0.0
    metadata: Mapping[str, Any] = field(default_factory=dict)
    step_id: str = field(default_factory=lambda: new_id("mission-step"))
    step_order: int = 0


@dataclass(frozen=True)
class MissionPlan:
    brief_id: str
    objective: str
    lane: MissionLane
    northstar_alignment: str
    northstar_principle_ids: tuple[str, ...]
    strategy_tags: tuple[str, ...]
    steps: tuple[MissionStep, ...]
    budget: MissionBudget
    stop_conditions: tuple[str, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)
    mission_id: str = field(default_factory=lambda: new_id("mission"))
    plan_hash: str = ""
    created_at: str = ""


@dataclass(frozen=True)
class MissionDecision:
    mission_id: str
    decision: MissionDecisionType
    principal: str
    channel: str
    reason: str
    decision_id: str = field(default_factory=lambda: new_id("mission-decision"))
    decided_at: str = ""


@dataclass(frozen=True)
class MissionTransition:
    mission_id: str
    from_status: MissionStatus | None
    to_status: MissionStatus
    principal: str
    reason: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    transition_id: str = field(default_factory=lambda: new_id("mission-transition"))
    created_at: str = ""


@dataclass(frozen=True)
class MissionStepAttempt:
    mission_id: str
    step_id: str
    attempt_number: int
    status: MissionStepStatus
    action_id: str
    approval_id: str | None = None
    output: Any = None
    error: str | None = None
    failure_fingerprint: str | None = None
    estimated_cost_usd: float = 0.0
    metadata: Mapping[str, Any] = field(default_factory=dict)
    attempt_id: str = field(default_factory=lambda: new_id("mission-attempt"))
    started_at: str = ""
    completed_at: str | None = None


@dataclass(frozen=True)
class MissionValueEvidence:
    mission_id: str
    kind: MissionValueKind
    description: str
    source: str
    amount_usd: float | None = None
    external_reference: str | None = None
    related_evidence_id: str | None = None
    verified_by: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    evidence_id: str = field(default_factory=lambda: new_id("mission-value"))
    observed_at: str = ""


@dataclass(frozen=True)
class MissionOutcome:
    mission_id: str
    state: MissionOutcomeState
    achieved: bool
    summary: str
    claimed_value_usd: float
    realized_revenue_usd: float
    verified_revenue_usd: float
    evidence_ids: tuple[str, ...]
    lessons: tuple[str, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)
    outcome_id: str = field(default_factory=lambda: new_id("mission-outcome"))
    created_at: str = ""


@dataclass(frozen=True)
class MissionExecution:
    mission_id: str
    status: MissionStatus
    completed_step_ids: tuple[str, ...]
    current_step_id: str | None = None
    approval_id: str | None = None
    blockers: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)


class MissionError(RuntimeError):
    pass


class MissionNotFound(MissionError):
    pass


class MissionBlocked(MissionError):
    def __init__(self, blockers: Sequence[str]):
        self.blockers = tuple(blockers)
        super().__init__("mission blocked: " + "; ".join(self.blockers))


class MissionDecisionConflict(MissionError):
    pass


@runtime_checkable
class MissionActionExecutor(Protocol):
    async def execute(self, proposal: ActionProposal) -> ActionResult: ...

    async def approval_result(self, approval_id: str) -> ActionResult | None: ...


def _safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (tuple, list, set)):
        return [_safe(v) for v in value]
    if hasattr(value, "value"):
        return _safe(value.value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def evidence_hash(source: str, statement: str, external_reference: str | None) -> str:
    raw = json.dumps(
        {"source": source.strip(), "statement": " ".join(statement.split()), "external_reference": external_reference or ""},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def opportunity_brief_hash(brief: ExpectedValueBrief) -> str:
    payload = {
        "title": " ".join(brief.title.casefold().split()),
        "lane": brief.lane.value,
        "problem": " ".join(brief.problem_statement.casefold().split()),
        "beneficiary": " ".join(brief.beneficiary.casefold().split()),
        "value_proposition": " ".join(brief.value_proposition.casefold().split()),
        "probability_success": round(brief.probability_success, 8),
        "upside_usd": round(brief.upside_usd, 8),
        "estimated_cost_usd": round(brief.estimated_cost_usd, 8),
        "evidence": sorted((item.evidence_id, item.content_hash, item.stance.value) for item in brief.evidence),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def mission_plan_hash(plan: MissionPlan) -> str:
    payload = mission_plan_payload(plan)
    payload.pop("created_at", None)
    payload.pop("plan_hash", None)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def opportunity_brief_payload(brief: ExpectedValueBrief) -> dict[str, Any]:
    return {
        "brief_id": brief.brief_id,
        "title": brief.title,
        "lane": brief.lane.value,
        "problem_statement": brief.problem_statement,
        "beneficiary": brief.beneficiary,
        "value_proposition": brief.value_proposition,
        "probability_success": brief.probability_success,
        "upside_usd": brief.upside_usd,
        "estimated_cost_usd": brief.estimated_cost_usd,
        "estimated_duration_hours": brief.estimated_duration_hours,
        "expected_net_value_usd": brief.expected_net_value_usd,
        "revenue_hypothesis": brief.revenue_hypothesis,
        "assumptions": list(brief.assumptions),
        "evidence": [
            {
                "evidence_id": e.evidence_id,
                "source": e.source,
                "statement": e.statement,
                "stance": e.stance.value,
                "observed_at": e.observed_at,
                "external_reference": e.external_reference,
                "independent_source_id": e.independent_source_id,
                "verified": e.verified,
                "metadata": _safe(e.metadata),
                "content_hash": e.content_hash,
            }
            for e in brief.evidence
        ],
        "contradiction_evidence_ids": list(brief.contradiction_evidence_ids),
        "independent_support_count": brief.independent_support_count,
        "risk": brief.risk.value,
        "confidence": brief.confidence,
        "blockers": list(brief.blockers),
        "metadata": _safe(brief.metadata),
        "brief_hash": brief.brief_hash,
        "created_at": brief.created_at,
    }


def opportunity_brief_from_payload(data: Mapping[str, Any]) -> ExpectedValueBrief:
    evidence = tuple(
        OpportunityEvidence(
            evidence_id=str(e["evidence_id"]),
            source=str(e["source"]),
            statement=str(e["statement"]),
            stance=OpportunityEvidenceStance(str(e.get("stance") or "supports")),
            observed_at=str(e.get("observed_at") or ""),
            external_reference=e.get("external_reference"),
            independent_source_id=e.get("independent_source_id"),
            verified=bool(e.get("verified", False)),
            metadata=dict(e.get("metadata") or {}),
            content_hash=str(e.get("content_hash") or ""),
        )
        for e in data.get("evidence") or ()
    )
    return ExpectedValueBrief(
        brief_id=str(data["brief_id"]), title=str(data["title"]), lane=MissionLane(str(data["lane"])),
        problem_statement=str(data["problem_statement"]), beneficiary=str(data["beneficiary"]),
        value_proposition=str(data["value_proposition"]), probability_success=float(data["probability_success"]),
        upside_usd=float(data["upside_usd"]), estimated_cost_usd=float(data["estimated_cost_usd"]),
        estimated_duration_hours=float(data["estimated_duration_hours"]), expected_net_value_usd=float(data["expected_net_value_usd"]),
        revenue_hypothesis=str(data.get("revenue_hypothesis") or ""), assumptions=tuple(str(v) for v in data.get("assumptions") or ()),
        evidence=evidence, contradiction_evidence_ids=tuple(str(v) for v in data.get("contradiction_evidence_ids") or ()),
        independent_support_count=int(data.get("independent_support_count", 0)), risk=MissionRisk(str(data.get("risk") or "medium")),
        confidence=float(data.get("confidence", 0.5)), blockers=tuple(str(v) for v in data.get("blockers") or ()),
        metadata=dict(data.get("metadata") or {}), brief_hash=str(data.get("brief_hash") or ""), created_at=str(data.get("created_at") or ""),
    )


def mission_plan_payload(plan: MissionPlan) -> dict[str, Any]:
    return {
        "mission_id": plan.mission_id, "brief_id": plan.brief_id, "objective": plan.objective,
        "lane": plan.lane.value, "northstar_alignment": plan.northstar_alignment,
        "northstar_principle_ids": list(plan.northstar_principle_ids), "strategy_tags": list(plan.strategy_tags),
        "steps": [
            {
                "step_id": s.step_id, "step_order": s.step_order, "title": s.title,
                "action": proposal_payload(s.action), "success_criteria": list(s.success_criteria),
                "depends_on": list(s.depends_on), "max_attempts": s.max_attempts,
                "stop_on_failure": s.stop_on_failure, "explicit_retry_reason": s.explicit_retry_reason,
                "estimated_cost_usd": s.estimated_cost_usd, "metadata": _safe(s.metadata),
            }
            for s in plan.steps
        ],
        "budget": {
            "max_cost_usd": plan.budget.max_cost_usd,
            "max_duration_seconds": plan.budget.max_duration_seconds,
            "max_step_attempts": plan.budget.max_step_attempts,
            "max_high_risk_actions": plan.budget.max_high_risk_actions,
            "minimum_expected_value_usd": plan.budget.minimum_expected_value_usd,
        },
        "stop_conditions": list(plan.stop_conditions), "metadata": _safe(plan.metadata),
        "plan_hash": plan.plan_hash, "created_at": plan.created_at,
    }


def mission_plan_from_payload(data: Mapping[str, Any]) -> MissionPlan:
    budget_data = dict(data.get("budget") or {})
    budget = MissionBudget(
        max_cost_usd=float(budget_data.get("max_cost_usd", 10.0)),
        max_duration_seconds=int(budget_data.get("max_duration_seconds", 3600)),
        max_step_attempts=int(budget_data.get("max_step_attempts", 10)),
        max_high_risk_actions=int(budget_data.get("max_high_risk_actions", 0)),
        minimum_expected_value_usd=float(budget_data.get("minimum_expected_value_usd", 0.0)),
    )
    steps = tuple(
        MissionStep(
            step_id=str(s["step_id"]), step_order=int(s.get("step_order", 0)), title=str(s["title"]),
            action=proposal_from_payload(dict(s["action"])), success_criteria=tuple(str(v) for v in s.get("success_criteria") or ()),
            depends_on=tuple(str(v) for v in s.get("depends_on") or ()), max_attempts=int(s.get("max_attempts", 1)),
            stop_on_failure=bool(s.get("stop_on_failure", True)), explicit_retry_reason=s.get("explicit_retry_reason"),
            estimated_cost_usd=float(s.get("estimated_cost_usd", 0.0)), metadata=dict(s.get("metadata") or {}),
        )
        for s in data.get("steps") or ()
    )
    return MissionPlan(
        mission_id=str(data["mission_id"]), brief_id=str(data["brief_id"]), objective=str(data["objective"]),
        lane=MissionLane(str(data["lane"])), northstar_alignment=str(data["northstar_alignment"]),
        northstar_principle_ids=tuple(str(v) for v in data.get("northstar_principle_ids") or ()),
        strategy_tags=tuple(str(v) for v in data.get("strategy_tags") or ()), steps=steps, budget=budget,
        stop_conditions=tuple(str(v) for v in data.get("stop_conditions") or ()), metadata=dict(data.get("metadata") or {}),
        plan_hash=str(data.get("plan_hash") or ""), created_at=str(data.get("created_at") or ""),
    )
