"""Provider-neutral contracts for autonomous opportunity intelligence and portfolio governance."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from aether.utils.ids import new_id


class SourceCapability(StrEnum):
    SEARCH = "search"
    FETCH = "fetch"
    CRAWL = "crawl"
    EXTRACT = "extract"
    CATALOG = "catalog"
    PLATFORM_READ = "platform-read"


class SourceKind(StrEnum):
    WEB = "web"
    SEARCH = "search"
    CATALOG = "catalog"
    FEED = "feed"
    PLATFORM = "platform"
    REPOSITORY = "repository"


class SourceHealth(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"


class EvidenceStrength(StrEnum):
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"
    VERIFIED = "verified"


class ClaimStance(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    CONTEXT = "context"


class OpportunityStatus(StrEnum):
    OBSERVED = "observed"
    EVIDENCE_REQUIRED = "evidence-required"
    PORTFOLIO_READY = "portfolio-ready"
    SELECTED = "selected"
    DEFERRED = "deferred"
    REJECTED = "rejected"
    CONVERTED_TO_MISSION = "converted-to-mission"


class PortfolioDecisionType(StrEnum):
    SELECT = "select"
    DEFER = "defer"
    REJECT = "reject"


class AutonomyLevel(StrEnum):
    OBSERVE = "observe"
    SYNTHESIZE = "synthesize"
    SANDBOX_EXPERIMENT = "sandbox-experiment"
    BOUNDED_EXTERNAL = "bounded-external"
    HIGH_CONSEQUENCE = "high-consequence"


class MandateStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    CONSUMED = "consumed"


@dataclass(frozen=True)
class SourceAdapterManifest:
    source_id: str
    adapter_id: str
    name: str
    kind: SourceKind
    capabilities: tuple[SourceCapability, ...]
    priority: int = 100
    public_observation: bool = True
    requires_credentials: bool = False
    allowed_domains: tuple[str, ...] = field(default_factory=tuple)
    forbidden_capabilities: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    manifest_hash: str = ""


@dataclass(frozen=True)
class SourceAdapterStatus:
    source_id: str
    adapter_id: str
    health: SourceHealth
    reason: str
    version: str = ""
    checked_at: str = ""
    latency_ms: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScoutQuery:
    objective: str
    queries: tuple[str, ...]
    source_kinds: tuple[SourceKind, ...] = field(default_factory=tuple)
    maximum_sources: int = 12
    maximum_snapshots: int = 40
    maximum_bytes: int = 4_000_000
    maximum_duration_seconds: int = 300
    allowed_domains: tuple[str, ...] = field(default_factory=tuple)
    blocked_domains: tuple[str, ...] = field(default_factory=tuple)
    autonomy_level: AutonomyLevel = AutonomyLevel.OBSERVE
    metadata: Mapping[str, Any] = field(default_factory=dict)
    query_id: str = field(default_factory=lambda: new_id("scout-query"))


@dataclass(frozen=True)
class SearchHit:
    source_id: str
    url: str
    title: str
    snippet: str
    rank: int
    query: str
    observed_at: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    hit_id: str = field(default_factory=lambda: new_id("search-hit"))


@dataclass(frozen=True)
class ContentSnapshot:
    source_id: str
    adapter_id: str
    canonical_url: str
    title: str
    content_text: str
    content_type: str
    retrieved_at: str
    content_hash: str
    raw_hash: str = ""
    status_code: int = 200
    redirect_chain: tuple[str, ...] = field(default_factory=tuple)
    policy_fingerprint: str = ""
    source_reference: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    snapshot_id: str = field(default_factory=lambda: new_id("snapshot"))


@dataclass(frozen=True)
class ExtractedClaim:
    snapshot_id: str
    source_id: str
    statement: str
    stance: ClaimStance
    subject: str
    confidence: float
    evidence_strength: EvidenceStrength
    observed_at: str
    external_reference: str | None = None
    extractor_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    claim_id: str = field(default_factory=lambda: new_id("claim"))
    claim_hash: str = ""


@dataclass(frozen=True)
class OpportunityScore:
    expected_net_value_usd: float
    evidence_confidence: float
    strategic_alignment: float
    reversibility: float
    time_to_validation: float
    execution_cost_penalty: float
    legal_risk_penalty: float
    platform_dependency_penalty: float
    saturation_penalty: float
    utility_score: float


@dataclass(frozen=True)
class OpportunityCandidate:
    title: str
    problem_statement: str
    beneficiary: str
    value_proposition: str
    revenue_hypothesis: str
    category: str
    claim_ids: tuple[str, ...]
    supporting_source_ids: tuple[str, ...]
    contradicting_claim_ids: tuple[str, ...]
    assumptions: tuple[str, ...]
    score: OpportunityScore
    expected_upside_usd: float
    probability_success: float
    estimated_cost_usd: float
    estimated_duration_hours: float
    risk: str
    status: OpportunityStatus
    blockers: tuple[str, ...] = field(default_factory=tuple)
    strategy_tags: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    candidate_id: str = field(default_factory=lambda: new_id("opportunity"))
    candidate_hash: str = ""
    created_at: str = ""


@dataclass(frozen=True)
class PortfolioPolicy:
    maximum_selected_candidates: int = 3
    maximum_total_experiment_budget_usd: float = 100.0
    maximum_high_risk_candidates: int = 1
    maximum_single_category_fraction: float = 0.5
    minimum_independent_sources: int = 2
    minimum_evidence_confidence: float = 0.45
    minimum_utility_score: float = 0.0
    reserved_exploration_fraction: float = 0.2

    def validate(self) -> None:
        if self.maximum_selected_candidates < 1:
            raise ValueError("maximum_selected_candidates must be positive")
        if self.maximum_total_experiment_budget_usd < 0:
            raise ValueError("maximum_total_experiment_budget_usd cannot be negative")
        for value, name in (
            (self.maximum_single_category_fraction, "maximum_single_category_fraction"),
            (self.minimum_evidence_confidence, "minimum_evidence_confidence"),
            (self.reserved_exploration_fraction, "reserved_exploration_fraction"),
        ):
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass(frozen=True)
class PortfolioSelection:
    candidate_ids: tuple[str, ...]
    rejected_candidate_ids: tuple[str, ...]
    deferred_candidate_ids: tuple[str, ...]
    allocated_budget_usd: float
    policy_fingerprint: str
    rationale: tuple[str, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)
    selection_id: str = field(default_factory=lambda: new_id("portfolio-selection"))
    created_at: str = ""


@dataclass(frozen=True)
class PortfolioDecision:
    candidate_id: str
    decision: PortfolioDecisionType
    principal: str
    reason: str
    allocated_budget_usd: float = 0.0
    channel: str = "operator"
    decision_id: str = field(default_factory=lambda: new_id("portfolio-decision"))
    decided_at: str = ""


@dataclass(frozen=True)
class ExperimentMandate:
    candidate_id: str
    principal: str
    autonomy_level: AutonomyLevel
    allowed_capabilities: tuple[str, ...]
    forbidden_capabilities: tuple[str, ...]
    maximum_cost_usd: float
    maximum_external_actions: int
    maximum_duration_seconds: int
    reversible_only: bool
    expires_at: str
    reason: str
    status: MandateStatus = MandateStatus.ACTIVE
    mandate_id: str = field(default_factory=lambda: new_id("experiment-mandate"))
    issued_at: str = ""
    mandate_hash: str = ""


@dataclass(frozen=True)
class ScoutRunReceipt:
    query_id: str
    status: str
    source_ids: tuple[str, ...]
    snapshot_ids: tuple[str, ...]
    claim_ids: tuple[str, ...]
    candidate_ids: tuple[str, ...]
    bytes_consumed: int
    duration_seconds: float
    blockers: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    run_id: str = field(default_factory=lambda: new_id("scout-run"))
    started_at: str = ""
    completed_at: str = ""


class OpportunityError(RuntimeError):
    pass


class OpportunityNotFound(OpportunityError):
    pass


class OpportunityBlocked(OpportunityError):
    def __init__(self, blockers: Sequence[str]):
        self.blockers = tuple(blockers)
        super().__init__("opportunity blocked: " + "; ".join(self.blockers))


class PortfolioDecisionConflict(OpportunityError):
    pass


@runtime_checkable
class SourceAdapter(Protocol):
    @property
    def manifest(self) -> SourceAdapterManifest: ...

    async def health(self) -> SourceAdapterStatus: ...

    async def search(self, query: ScoutQuery) -> Sequence[SearchHit]: ...

    async def fetch(self, hit: SearchHit, query: ScoutQuery) -> ContentSnapshot: ...


@runtime_checkable
class ClaimExtractor(Protocol):
    extractor_id: str

    async def extract(self, snapshot: ContentSnapshot, query: ScoutQuery) -> Sequence[ExtractedClaim]: ...


def _safe(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_safe(v) for v in value]
    return value


def canonical_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(_safe(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def source_manifest_hash(item: SourceAdapterManifest) -> str:
    return canonical_hash({
        "source_id": item.source_id,
        "adapter_id": item.adapter_id,
        "name": item.name,
        "kind": item.kind,
        "capabilities": item.capabilities,
        "priority": item.priority,
        "public_observation": item.public_observation,
        "requires_credentials": item.requires_credentials,
        "allowed_domains": item.allowed_domains,
        "forbidden_capabilities": item.forbidden_capabilities,
        "metadata": item.metadata,
    })


def claim_hash(item: ExtractedClaim) -> str:
    return canonical_hash({
        "source_id": item.source_id,
        "statement": " ".join(item.statement.casefold().split()),
        "stance": item.stance,
        "subject": " ".join(item.subject.casefold().split()),
        "external_reference": item.external_reference,
    })


def opportunity_candidate_hash(item: OpportunityCandidate) -> str:
    return canonical_hash({
        "title": " ".join(item.title.casefold().split()),
        "problem_statement": " ".join(item.problem_statement.casefold().split()),
        "beneficiary": " ".join(item.beneficiary.casefold().split()),
        "category": item.category.casefold(),
        "claim_ids": sorted(item.claim_ids),
        "expected_upside_usd": item.expected_upside_usd,
        "probability_success": item.probability_success,
        "estimated_cost_usd": item.estimated_cost_usd,
    })


def portfolio_policy_fingerprint(item: PortfolioPolicy) -> str:
    return canonical_hash(item.__dict__)


def mandate_hash(item: ExperimentMandate) -> str:
    return canonical_hash({
        "candidate_id": item.candidate_id,
        "principal": item.principal,
        "autonomy_level": item.autonomy_level,
        "allowed_capabilities": item.allowed_capabilities,
        "forbidden_capabilities": item.forbidden_capabilities,
        "maximum_cost_usd": item.maximum_cost_usd,
        "maximum_external_actions": item.maximum_external_actions,
        "maximum_duration_seconds": item.maximum_duration_seconds,
        "reversible_only": item.reversible_only,
        "expires_at": item.expires_at,
        "reason": item.reason,
    })


def opportunity_score_payload(item: OpportunityScore) -> dict[str, Any]:
    return {key: float(value) for key, value in item.__dict__.items()}


def source_manifest_payload(item: SourceAdapterManifest) -> dict[str, Any]:
    return {
        "source_id": item.source_id, "adapter_id": item.adapter_id, "name": item.name,
        "kind": item.kind.value, "capabilities": [v.value for v in item.capabilities],
        "priority": item.priority, "public_observation": item.public_observation,
        "requires_credentials": item.requires_credentials, "allowed_domains": list(item.allowed_domains),
        "forbidden_capabilities": list(item.forbidden_capabilities), "metadata": dict(item.metadata),
        "manifest_hash": item.manifest_hash,
    }


def source_manifest_from_payload(data: Mapping[str, Any]) -> SourceAdapterManifest:
    return SourceAdapterManifest(
        source_id=str(data["source_id"]), adapter_id=str(data["adapter_id"]), name=str(data["name"]),
        kind=SourceKind(str(data["kind"])), capabilities=tuple(SourceCapability(str(v)) for v in data.get("capabilities", ())),
        priority=int(data.get("priority", 100)), public_observation=bool(data.get("public_observation", True)),
        requires_credentials=bool(data.get("requires_credentials", False)),
        allowed_domains=tuple(str(v) for v in data.get("allowed_domains", ())),
        forbidden_capabilities=tuple(str(v) for v in data.get("forbidden_capabilities", ())),
        metadata=dict(data.get("metadata", {})), manifest_hash=str(data.get("manifest_hash", "")),
    )


def content_snapshot_payload(item: ContentSnapshot) -> dict[str, Any]:
    return {
        "source_id": item.source_id, "adapter_id": item.adapter_id, "canonical_url": item.canonical_url,
        "title": item.title, "content_text": item.content_text, "content_type": item.content_type,
        "retrieved_at": item.retrieved_at, "content_hash": item.content_hash, "raw_hash": item.raw_hash,
        "status_code": item.status_code, "redirect_chain": list(item.redirect_chain),
        "policy_fingerprint": item.policy_fingerprint, "source_reference": item.source_reference,
        "metadata": dict(item.metadata), "snapshot_id": item.snapshot_id,
    }


def content_snapshot_from_payload(data: Mapping[str, Any]) -> ContentSnapshot:
    return ContentSnapshot(
        source_id=str(data["source_id"]), adapter_id=str(data["adapter_id"]), canonical_url=str(data["canonical_url"]),
        title=str(data.get("title", "")), content_text=str(data.get("content_text", "")),
        content_type=str(data.get("content_type", "text/plain")), retrieved_at=str(data.get("retrieved_at", "")),
        content_hash=str(data["content_hash"]), raw_hash=str(data.get("raw_hash", "")),
        status_code=int(data.get("status_code", 200)), redirect_chain=tuple(str(v) for v in data.get("redirect_chain", ())),
        policy_fingerprint=str(data.get("policy_fingerprint", "")), source_reference=data.get("source_reference"),
        metadata=dict(data.get("metadata", {})), snapshot_id=str(data["snapshot_id"]),
    )


def extracted_claim_payload(item: ExtractedClaim) -> dict[str, Any]:
    return {
        "snapshot_id": item.snapshot_id, "source_id": item.source_id, "statement": item.statement,
        "stance": item.stance.value, "subject": item.subject, "confidence": item.confidence,
        "evidence_strength": item.evidence_strength.value, "observed_at": item.observed_at,
        "external_reference": item.external_reference, "extractor_id": item.extractor_id,
        "metadata": dict(item.metadata), "claim_id": item.claim_id, "claim_hash": item.claim_hash,
    }


def extracted_claim_from_payload(data: Mapping[str, Any]) -> ExtractedClaim:
    return ExtractedClaim(
        snapshot_id=str(data["snapshot_id"]), source_id=str(data["source_id"]), statement=str(data["statement"]),
        stance=ClaimStance(str(data["stance"])), subject=str(data["subject"]), confidence=float(data["confidence"]),
        evidence_strength=EvidenceStrength(str(data["evidence_strength"])), observed_at=str(data.get("observed_at", "")),
        external_reference=data.get("external_reference"), extractor_id=str(data.get("extractor_id", "")),
        metadata=dict(data.get("metadata", {})), claim_id=str(data["claim_id"]), claim_hash=str(data.get("claim_hash", "")),
    )


def opportunity_candidate_payload(item: OpportunityCandidate) -> dict[str, Any]:
    return {
        "title": item.title, "problem_statement": item.problem_statement, "beneficiary": item.beneficiary,
        "value_proposition": item.value_proposition, "revenue_hypothesis": item.revenue_hypothesis,
        "category": item.category, "claim_ids": list(item.claim_ids),
        "supporting_source_ids": list(item.supporting_source_ids),
        "contradicting_claim_ids": list(item.contradicting_claim_ids), "assumptions": list(item.assumptions),
        "score": opportunity_score_payload(item.score), "expected_upside_usd": item.expected_upside_usd,
        "probability_success": item.probability_success, "estimated_cost_usd": item.estimated_cost_usd,
        "estimated_duration_hours": item.estimated_duration_hours, "risk": item.risk,
        "status": item.status.value, "blockers": list(item.blockers), "strategy_tags": list(item.strategy_tags),
        "metadata": dict(item.metadata), "candidate_id": item.candidate_id,
        "candidate_hash": item.candidate_hash, "created_at": item.created_at,
    }


def opportunity_candidate_from_payload(data: Mapping[str, Any]) -> OpportunityCandidate:
    return OpportunityCandidate(
        title=str(data["title"]), problem_statement=str(data["problem_statement"]), beneficiary=str(data["beneficiary"]),
        value_proposition=str(data["value_proposition"]), revenue_hypothesis=str(data["revenue_hypothesis"]),
        category=str(data["category"]), claim_ids=tuple(str(v) for v in data.get("claim_ids", ())),
        supporting_source_ids=tuple(str(v) for v in data.get("supporting_source_ids", ())),
        contradicting_claim_ids=tuple(str(v) for v in data.get("contradicting_claim_ids", ())),
        assumptions=tuple(str(v) for v in data.get("assumptions", ())),
        score=OpportunityScore(**{k: float(v) for k, v in dict(data["score"]).items()}),
        expected_upside_usd=float(data["expected_upside_usd"]), probability_success=float(data["probability_success"]),
        estimated_cost_usd=float(data["estimated_cost_usd"]), estimated_duration_hours=float(data["estimated_duration_hours"]),
        risk=str(data["risk"]), status=OpportunityStatus(str(data["status"])),
        blockers=tuple(str(v) for v in data.get("blockers", ())), strategy_tags=tuple(str(v) for v in data.get("strategy_tags", ())),
        metadata=dict(data.get("metadata", {})), candidate_id=str(data["candidate_id"]),
        candidate_hash=str(data.get("candidate_hash", "")), created_at=str(data.get("created_at", "")),
    )


def experiment_mandate_payload(item: ExperimentMandate) -> dict[str, Any]:
    return {
        "candidate_id": item.candidate_id, "principal": item.principal, "autonomy_level": item.autonomy_level.value,
        "allowed_capabilities": list(item.allowed_capabilities), "forbidden_capabilities": list(item.forbidden_capabilities),
        "maximum_cost_usd": item.maximum_cost_usd, "maximum_external_actions": item.maximum_external_actions,
        "maximum_duration_seconds": item.maximum_duration_seconds, "reversible_only": item.reversible_only,
        "expires_at": item.expires_at, "reason": item.reason, "status": item.status.value,
        "mandate_id": item.mandate_id, "issued_at": item.issued_at, "mandate_hash": item.mandate_hash,
    }


def experiment_mandate_from_payload(data: Mapping[str, Any]) -> ExperimentMandate:
    return ExperimentMandate(
        candidate_id=str(data["candidate_id"]), principal=str(data["principal"]),
        autonomy_level=AutonomyLevel(str(data["autonomy_level"])),
        allowed_capabilities=tuple(str(v) for v in data.get("allowed_capabilities", ())),
        forbidden_capabilities=tuple(str(v) for v in data.get("forbidden_capabilities", ())),
        maximum_cost_usd=float(data["maximum_cost_usd"]), maximum_external_actions=int(data["maximum_external_actions"]),
        maximum_duration_seconds=int(data["maximum_duration_seconds"]), reversible_only=bool(data["reversible_only"]),
        expires_at=str(data["expires_at"]), reason=str(data["reason"]), status=MandateStatus(str(data.get("status", "active"))),
        mandate_id=str(data["mandate_id"]), issued_at=str(data.get("issued_at", "")), mandate_hash=str(data.get("mandate_hash", "")),
    )
