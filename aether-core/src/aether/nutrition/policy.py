"""Deterministic policy checks for external nutrition candidates."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import yaml

from aether.contracts.nutrition import (
    ExternalNutritionCandidate,
    NutritionActivationState,
    NutritionConformanceCheck,
)

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")


class NutritionPolicy:
    def __init__(self, policy_path: Path | None = None) -> None:
        self.policy_path = policy_path or Path(__file__).with_name("nutrition_conformance.yaml")
        self.data = yaml.safe_load(self.policy_path.read_text(encoding="utf-8")) or {}

    @property
    def mandatory_adapter_denials(self) -> tuple[str, ...]:
        return tuple(self.data.get("mandatory_adapter_denials", ()))

    def validate_candidate(self, candidate: ExternalNutritionCandidate) -> tuple[NutritionConformanceCheck, ...]:
        forbidden = self.data.get("forbidden", {})
        allowed_states = {
            NutritionActivationState(value)
            for value in self.data.get("candidate", {}).get("allowed_activation_states", ())
        }
        checks: list[NutritionConformanceCheck] = []

        checks.append(self._check(
            "immutable-commit-pin",
            bool(_SHA40.fullmatch(candidate.commit_sha.casefold())),
            "candidate is pinned to an exact 40-character commit SHA",
            {"commit_sha": candidate.commit_sha},
        ))
        checks.append(self._check(
            "artifact-sha256",
            bool(_SHA64.fullmatch(candidate.artifact_hash.casefold())),
            "candidate artifact has an exact SHA-256 identity",
            {"artifact_hash": candidate.artifact_hash},
        ))
        license_name = candidate.license.strip().casefold()
        checks.append(self._check(
            "declared-license",
            bool(license_name) and license_name not in {"unknown", "none", "unlicensed", "n/a"},
            "candidate declares a reviewable license",
            {"license": candidate.license},
        ))
        checks.append(self._check(
            "source-provenance",
            bool(candidate.repository.strip() and candidate.artifact_path.strip() and candidate.publisher.strip()),
            "repository, artifact path, and publisher are declared",
        ))
        checks.append(self._check(
            "normalization-target",
            bool(candidate.normalization_target.strip()),
            "candidate is normalized into an Aether-owned capability instead of direct installation",
            {"target": candidate.normalization_target},
        ))
        checks.append(self._check(
            "deterministic-check-plan",
            bool(candidate.deterministic_checks),
            "candidate includes deterministic checks",
            {"count": len(candidate.deterministic_checks)},
        ))
        checks.append(self._check(
            "heldout-check-plan",
            bool(candidate.heldout_checks),
            "candidate includes held-out checks",
            {"count": len(candidate.heldout_checks)},
        ))
        checks.append(self._check(
            "source-adapter-binding",
            bool(candidate.required_adapter_ids) and bool(candidate.requested_source_capabilities),
            "candidate declares source adapters and requested source capabilities",
            {
                "adapter_ids": list(candidate.required_adapter_ids),
                "capabilities": [value.value for value in candidate.requested_source_capabilities],
            },
        ))
        checks.append(self._check(
            "candidate-state-not-active",
            candidate.activation_state in allowed_states,
            "nutrition conformance accepts intake/benchmark states only; it never authorizes activation",
            {"activation_state": candidate.activation_state.value},
        ))

        for field_name, values in (
            ("side_effects", candidate.side_effects),
            ("runtime_requirements", candidate.runtime_requirements),
            ("credential_requirements", candidate.credential_requirements),
            ("install_behavior", candidate.install_behavior),
            ("update_behavior", candidate.update_behavior),
        ):
            blocked = self._blocked(values, forbidden.get(field_name, ()))
            checks.append(self._check(
                f"{field_name.replace('_', '-')}-boundary",
                not blocked,
                f"{field_name} contains no forbidden host authority",
                {"blocked": list(blocked)},
            ))

        network_blocked = self._blocked(candidate.network_destinations, forbidden.get("network_destinations", ()))
        checks.append(self._check(
            "network-destination-boundary",
            not network_blocked and all(self._public_destination(value) for value in candidate.network_destinations),
            "network destinations are explicit public HTTP(S) origins or empty",
            {"blocked": list(network_blocked), "destinations": list(candidate.network_destinations)},
        ))
        return tuple(checks)

    @staticmethod
    def _blocked(values: Iterable[str], forbidden: Iterable[str]) -> tuple[str, ...]:
        forbidden_values = tuple(item.casefold().strip() for item in forbidden)
        blocked: list[str] = []
        for value in values:
            normalized = value.casefold().strip()
            if any(item and (normalized == item or item in normalized) for item in forbidden_values):
                blocked.append(value)
        return tuple(blocked)

    @staticmethod
    def _public_destination(value: str) -> bool:
        if not value:
            return False
        lowered = value.casefold().strip()
        return lowered.startswith("https://") or lowered.startswith("http://")

    @staticmethod
    def _check(name: str, passed: bool, detail: str, evidence=None) -> NutritionConformanceCheck:
        return NutritionConformanceCheck(name, bool(passed), detail, evidence or {})
