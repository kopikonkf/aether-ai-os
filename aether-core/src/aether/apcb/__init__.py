"""Aether Principal Coordination Bridge (APCB) — Slice A contracts and config.

APCB v0.1 implementation contract:
  project-docs/architecture/APCB_V0_1_IMPLEMENTATION_CONTRACT.md

Slice A scope (contracts/config only, NO runtime dispatch logic):
  - principal profile registry (Aether-owned, loaded from YAML);
  - bridge execution receipt contract (idempotency tuple);
  - principal handoff artifact contract;
  - APCB service identity configuration.

Design invariants (ADR-0056 / contract):
  - Aether remains canonical authority; APCB is deterministic glue only.
  - principal_id is identity/attribution, never authorization.
  - role never implies mutation authority.
  - No parallel coordination datastore; receipts are bounded and keyed by
    (work_id, attempt_number, principal_id).
"""
from __future__ import annotations

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
from .profiles import (
    ExecutionProfile,
    PrincipalProfile,
    PrincipalRuntimeProfiles,
    load_principal_profiles,
)

__all__ = [
    "APCBServiceIdentity",
    "BridgeExecutionReceipt",
    "DispatchEligibility",
    "ExecutionProfile",
    "ExecutionReceiptStatus",
    "PrincipalHandoff",
    "PrincipalProfile",
    "PrincipalRuntimeProfiles",
    "PromptEnvelope",
    "ReceiptIdempotencyKey",
    "dispatch_eligibility_key",
    "execution_receipt_key",
    "load_principal_profiles",
]
