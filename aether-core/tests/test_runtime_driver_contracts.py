from __future__ import annotations

import pytest

from aether.contracts import (
    AETHER_CODING_STREAM_PROTOCOL,
    RuntimeDriverImplementation,
    RuntimeDriverManifest,
)


def _manifest(**changes):
    data = dict(
        driver_id="openai-codex-cli",
        display_name="OpenAI Codex CLI",
        vendor="OpenAI",
        implementation=RuntimeDriverImplementation.LIVE,
        protocol=AETHER_CODING_STREAM_PROTOCOL,
        routing_key="runtime://coding/openai-codex-cli",
        adapter_id="runtime.coding.openai-codex-cli",
        executable_candidates=("codex",),
        version_argv=("--version",),
        operations=("coding.task.execute",),
        capabilities=("coding.patch-generation",),
        runtime_features=("generative-coding",),
        supported_platforms=("linux", "darwin", "windows"),
        credential_env_names=("OPENAI_API_KEY", "CODEX_HOME"),
        priority=3,
        enabled_by_default=True,
    )
    data.update(changes)
    return RuntimeDriverManifest(**data)


def test_runtime_driver_manifest_has_stable_fingerprint():
    first = _manifest()
    second = _manifest()
    first.validate()
    assert first.fingerprint() == second.fingerprint()
    assert len(first.fingerprint()) == 64


def test_live_driver_requires_executable_and_operation():
    with pytest.raises(ValueError):
        _manifest(executable_candidates=()).validate()
    with pytest.raises(ValueError):
        _manifest(operations=()).validate()


def test_driver_credentials_are_names_not_values():
    manifest = _manifest()
    assert "OPENAI_API_KEY" in manifest.credential_env_names
    assert all("test" not in value.lower() for value in manifest.credential_env_names)


def test_conformance_receipt_binds_exact_runtime_and_suite():
    from aether.contracts import RuntimeConformanceCheck, RuntimeConformanceReceipt
    receipt = RuntimeConformanceReceipt(
        driver_id="opencode-cli",
        manifest_fingerprint="a" * 64,
        executable_path="/tmp/opencode",
        executable_sha256="b" * 64,
        runtime_version="1.18.4",
        protocol=AETHER_CODING_STREAM_PROTOCOL,
        provider_id="opencode-zen",
        model_id="opencode/north-mini-code-free",
        configuration_hash="c" * 64,
        suite_hash="d" * 64,
        issued_at="2026-07-28T00:00:00+00:00",
        expires_at="2026-07-29T00:00:00+00:00",
        checks=(RuntimeConformanceCheck("protocol-handshake", True, "ok"),),
        issued_by="founder",
    )
    assert receipt.passed is True
    assert len(receipt.fingerprint()) == 64
    assert receipt.fingerprint() == receipt.fingerprint()


def test_runtime_driver_pack_v3_activates_gemini_and_claude_without_vendor_logic_in_core():
    from importlib.resources import files
    import yaml
    policy = yaml.safe_load(files("aether.runtimes").joinpath("runtime_driver_pack.yaml").read_text(encoding="utf-8"))
    assert policy["version"] == 3
    assert policy["policy_id"] == "aether.runtime-driver-pack.v3"
    drivers = {item["driver_id"]: item for item in policy["drivers"]}
    assert drivers["google-gemini-cli"]["implementation"] == "live"
    assert drivers["anthropic-claude-code"]["implementation"] == "live"
    assert drivers["google-gemini-cli"]["translator_module"].endswith("gemini_cli")
    assert drivers["anthropic-claude-code"]["translator_module"].endswith("claude_code")
    assert "AETHER_GEMINI_API_KEY_FILE" in drivers["google-gemini-cli"]["credential_env_names"]
    assert "AETHER_CLAUDE_API_KEY_FILE" in drivers["anthropic-claude-code"]["credential_env_names"]


def test_runtime_quota_state_is_routing_evidence_not_authority():
    from aether.contracts import RuntimeQuotaState
    assert RuntimeQuotaState.RATE_LIMITED.value == "rate-limited"
    assert RuntimeQuotaState.QUOTA_EXHAUSTED.value == "quota-exhausted"
    assert "approve" not in {item.value for item in RuntimeQuotaState}


def test_operations_snapshot_keeps_governance_outside_driver_state():
    from aether.contracts import RuntimeOperationsDriverSnapshot, RuntimeQuotaState, RuntimeReliabilitySnapshot
    reliability = RuntimeReliabilitySnapshot("d", 0, 0, 0, 0, 0.0, 0, 0.5, 10, "2026-07-28T00:00:00+00:00")
    snapshot = RuntimeOperationsDriverSnapshot(
        driver_id="google-gemini-cli",
        availability=__import__("aether.contracts", fromlist=["RuntimeDriverAvailability"]).RuntimeDriverAvailability.AVAILABLE,
        conformance_state=__import__("aether.contracts", fromlist=["RuntimeConformanceState"]).RuntimeConformanceState.PASSED,
        routing_eligible=True,
        runtime_version="0.11.0",
        model_id="gemini-2.5-flash",
        provider_id="google-gemini",
        reliability=reliability,
        quota_state=RuntimeQuotaState.HEALTHY,
    )
    assert snapshot.routing_eligible is True
    assert not hasattr(snapshot, "approval")
