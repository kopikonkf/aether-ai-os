from __future__ import annotations

from dataclasses import replace

from aether.contracts import SourceCapability
from aether.contracts.nutrition import (
    ExternalNutritionCandidate,
    NutritionActivationState,
    external_nutrition_candidate_hash,
)
from aether.nutrition import NutritionPolicy


def _candidate() -> ExternalNutritionCandidate:
    return ExternalNutritionCandidate(
        repository="https://example.com/upstream/research-skill.git",
        commit_sha="a" * 40,
        artifact_path="SKILL.md",
        artifact_hash="b" * 64,
        license="MIT",
        publisher="example-publisher",
        requested_source_capabilities=(SourceCapability.SEARCH, SourceCapability.FETCH),
        required_adapter_ids=("adapter.search", "adapter.fetch"),
        normalization_target="recent-signal-research",
        deterministic_checks=("bounded-window", "provenance-present"),
        heldout_checks=("contradiction-fixture",),
        network_destinations=("https://example.com",),
        activation_state=NutritionActivationState.NORMALIZED,
    )


def test_safe_candidate_passes_static_nutrition_policy() -> None:
    checks = NutritionPolicy().validate_candidate(_candidate())
    assert checks
    assert all(check.passed for check in checks)
    assert len(external_nutrition_candidate_hash(_candidate())) == 64


def test_floating_or_malformed_source_identity_fails() -> None:
    candidate = replace(_candidate(), commit_sha="main", artifact_hash="short")
    failed = {check.name for check in NutritionPolicy().validate_candidate(candidate) if not check.passed}
    assert failed == {"immutable-commit-pin", "artifact-sha256"}


def test_direct_install_self_update_and_secret_extraction_fail() -> None:
    candidate = replace(
        _candidate(),
        side_effects=("arbitrary-shell", "browser-cookie-extraction"),
        credential_requirements=("raw-secret",),
        install_behavior=("direct-install",),
        update_behavior=("self-update",),
    )
    failed = {check.name for check in NutritionPolicy().validate_candidate(candidate) if not check.passed}
    assert {
        "side-effects-boundary",
        "credential-requirements-boundary",
        "install-behavior-boundary",
        "update-behavior-boundary",
    }.issubset(failed)


def test_active_candidate_cannot_use_nutrition_conformance_as_activation_authority() -> None:
    candidate = replace(_candidate(), activation_state=NutritionActivationState.ACTIVE)
    failed = {check.name for check in NutritionPolicy().validate_candidate(candidate) if not check.passed}
    assert "candidate-state-not-active" in failed


def test_benchmark_plans_and_normalization_target_are_required() -> None:
    candidate = replace(
        _candidate(),
        normalization_target="",
        deterministic_checks=(),
        heldout_checks=(),
        required_adapter_ids=(),
    )
    failed = {check.name for check in NutritionPolicy().validate_candidate(candidate) if not check.passed}
    assert {
        "normalization-target",
        "deterministic-check-plan",
        "heldout-check-plan",
        "source-adapter-binding",
    }.issubset(failed)
