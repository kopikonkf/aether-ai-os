"""Bind external nutrition candidates to exact source-adapter conformance evidence."""
from __future__ import annotations

from dataclasses import replace

from aether.contracts import (
    ExternalNutritionCandidate,
    NutritionConformanceCheck,
    NutritionConformanceReceipt,
    NutritionConformanceState,
    SourceConformanceState,
)
from aether.contracts.nutrition import (
    external_nutrition_candidate_hash,
    nutrition_conformance_receipt_hash,
)
from aether.nutrition import NutritionPolicy
from aether.utils.time import utc_now
from aether.web_intelligence import WebIntelligenceEngine
from aether_gateway.opportunities import SourceCapabilityMesh


class NutritionConformanceService:
    """Issue benchmark-eligibility receipts without granting activation authority."""

    def __init__(
        self,
        mesh: SourceCapabilityMesh,
        web_engine: WebIntelligenceEngine,
        *,
        policy: NutritionPolicy | None = None,
    ) -> None:
        self.mesh = mesh
        self.web_engine = web_engine
        self.policy = policy or NutritionPolicy()

    def conform(self, candidate: ExternalNutritionCandidate, *, principal: str) -> NutritionConformanceReceipt:
        checks = list(self.policy.validate_candidate(candidate))
        manifest_hashes: dict[str, str] = {}
        source_receipt_ids: list[str] = []
        capability_union = set()

        for adapter_id in candidate.required_adapter_ids:
            try:
                adapter = self.mesh.get(adapter_id)
            except KeyError:
                checks.append(NutritionConformanceCheck(
                    f"adapter:{adapter_id}:registered",
                    False,
                    "required source adapter is not registered",
                ))
                continue

            manifest = adapter.manifest
            manifest_hashes[adapter_id] = manifest.manifest_hash
            capability_union.update(manifest.capabilities)
            checks.append(NutritionConformanceCheck(
                f"adapter:{adapter_id}:manifest-hash",
                bool(manifest.manifest_hash),
                "adapter manifest has an immutable fingerprint",
                {"manifest_hash": manifest.manifest_hash},
            ))
            missing_denials = sorted(
                set(self.policy.mandatory_adapter_denials) - set(manifest.forbidden_capabilities)
            )
            checks.append(NutritionConformanceCheck(
                f"adapter:{adapter_id}:mandatory-denials",
                not missing_denials,
                "adapter denies mandatory private/local/credential authority",
                {"missing_denials": missing_denials},
            ))

            state = self.web_engine.effective_conformance(
                adapter_id, manifest_hash=manifest.manifest_hash
            )
            receipt = self.web_engine.store.latest_conformance(adapter_id)
            if receipt is not None:
                source_receipt_ids.append(receipt.receipt_id)
            checks.append(NutritionConformanceCheck(
                f"adapter:{adapter_id}:exact-conformance",
                state == SourceConformanceState.PASSED,
                "adapter has a current passed receipt bound to its exact manifest and configuration",
                {
                    "state": state.value,
                    "receipt_id": receipt.receipt_id if receipt else None,
                    "manifest_hash": manifest.manifest_hash,
                },
            ))

        missing_capabilities = sorted(
            value.value
            for value in set(candidate.requested_source_capabilities) - capability_union
        )
        checks.append(NutritionConformanceCheck(
            "requested-capability-coverage",
            not missing_capabilities,
            "registered conformed adapters cover all requested source capabilities",
            {"missing_capabilities": missing_capabilities},
        ))

        passed = all(check.passed for check in checks)
        candidate_hash = external_nutrition_candidate_hash(candidate)
        receipt = NutritionConformanceReceipt(
            candidate_id=candidate.candidate_id,
            candidate_hash=candidate_hash,
            state=NutritionConformanceState.PASSED if passed else NutritionConformanceState.FAILED,
            checks=tuple(checks),
            eligible_for_benchmark=passed,
            eligible_for_activation=False,
            required_adapter_manifest_hashes=manifest_hashes,
            source_conformance_receipt_ids=tuple(source_receipt_ids),
            issued_by=principal,
            issued_at=utc_now(),
            error=None if passed else "; ".join(check.name for check in checks if not check.passed),
            metadata={
                "activation_authority": "skill-factory-founder-decision-only",
                "external_material_role": "nutrition-candidate",
            },
        )
        return replace(
            receipt,
            receipt_hash=nutrition_conformance_receipt_hash(receipt),
        )
