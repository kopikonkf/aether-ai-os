"""Aether Principal Coordination Bridge (APCB) — contracts, config, adapter.

APCB v0.1 implementation contract:
  project-docs/architecture/APCB_V0_1_IMPLEMENTATION_CONTRACT.md

Slice A scope (contracts/config, no runtime dispatch):
  - principal profile registry (Aether-owned, loaded from YAML);
  - bridge execution receipt contract (idempotency tuple);
  - principal handoff artifact contract;
  - APCB service identity configuration.

Slice B scope (Herdr adapter + conformance gate + durable receipts):
  - conformance gate (hard gate: HEALTHY/VALID -> dispatch, else reject;
    NO forced fallback);
  - Herdr execution adapter (narrow CLI glue, opaque execution refs);
  - append-only receipt store keyed by (work_id, attempt_number, principal_id);
  - DispatchEligibility all-or-nothing evaluator;
  - deterministic dispatcher (eligibility -> receipt -> conformance ->
    dispatch -> observe -> reconcile) with observation-level state machine.

Design invariants (ADR-0056 / contract):
  - Aether remains canonical authority; APCB is deterministic glue only.
  - principal_id is identity/attribution, never authorization.
  - role never implies mutation authority.
  - No parallel coordination datastore; receipts are bounded and keyed by
    (work_id, attempt_number, principal_id).
"""
from __future__ import annotations

from .conformance import (
    AdapterConformance,
    AdapterConformanceStatus,
    ConformanceGate,
)
from .contracts import (
    APCBServiceIdentity,
    BridgeExecutionReceipt,
    DispatchEligibility,
    ExecutionReceiptStatus,
    PrincipalHandoff,
    PromptEnvelope,
    ReceiptIdempotencyKey,
    dispatch_eligibility_key,
    execution_receipt_key,
)
from .dispatcher import APCBDispatcher, DispatchDecision, WorkItemView
from .eligibility import EligibilityEvaluator
from .herdr_adapter import (
    AgentObservation,
    HerdrExecutionAdapter,
)
from .profiles import (
    ExecutionProfile,
    PrincipalProfile,
    PrincipalRuntimeProfiles,
    load_principal_profiles,
)
from .receipt_store import ReceiptStore

__all__ = [
    "APCBDispatcher",
    "APCBServiceIdentity",
    "AdapterConformance",
    "AdapterConformanceStatus",
    "AgentObservation",
    "BridgeExecutionReceipt",
    "ConformanceGate",
    "DispatchDecision",
    "DispatchEligibility",
    "EligibilityEvaluator",
    "ExecutionProfile",
    "ExecutionReceiptStatus",
    "HerdrExecutionAdapter",
    "PrincipalHandoff",
    "PrincipalProfile",
    "PrincipalRuntimeProfiles",
    "PromptEnvelope",
    "ReceiptIdempotencyKey",
    "ReceiptStore",
    "WorkItemView",
    "dispatch_eligibility_key",
    "execution_receipt_key",
    "load_principal_profiles",
]
