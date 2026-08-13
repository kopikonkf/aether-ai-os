"""APCB Slice B — conformance gate (hard gate, no forced fallback).

Chief-architect verdict:
  HEALTHY/VALID -> eligible (dispatch)
  EXPIRED       -> reject dispatch + diagnostic
  MISSING       -> reject dispatch + diagnostic
  unavailable   -> reject dispatch + diagnostic
"""
from __future__ import annotations

import pytest

from aether.apcb.conformance import (
    AdapterConformanceStatus,
    ConformanceGate,
)
from aether.apcb.profiles import PrincipalRuntimeProfiles


@pytest.fixture(scope="module")
def profiles() -> PrincipalRuntimeProfiles:
    return PrincipalRuntimeProfiles()


@pytest.fixture
def gate_factory(profiles):
    def make(status_by_kind):
        return ConformanceGate(profiles, probe=lambda kind: status_by_kind.get(kind, AdapterConformanceStatus.MISSING))
    return make


class TestConformanceGateHealthy:
    def test_healthy_eligible(self, gate_factory):
        gate = gate_factory({"freebuff": AdapterConformanceStatus.HEALTHY})
        c = gate.evaluate("claude", "herdr:freebuff")
        assert c.eligible is True
        assert c.status is AdapterConformanceStatus.HEALTHY
        assert c.herdr_agent_kind == "freebuff"
        assert c.diagnostic == ()

    def test_valid_eligible(self, gate_factory):
        gate = gate_factory({"opencode": AdapterConformanceStatus.VALID})
        c = gate.evaluate("chatgpt", "herdr:opencode")
        assert c.eligible is True
        assert c.status is AdapterConformanceStatus.VALID


class TestConformanceGateReject:
    def test_expired_rejects_with_diagnostic(self, gate_factory):
        gate = gate_factory({"opencode": AdapterConformanceStatus.EXPIRED})
        c = gate.evaluate("opencode", "herdr:opencode")
        assert c.eligible is False
        assert c.status is AdapterConformanceStatus.EXPIRED
        assert c.diagnostic, "EXPIRED must carry a diagnostic"

    def test_missing_rejects_with_diagnostic(self, gate_factory):
        gate = gate_factory({})  # nothing detected
        c = gate.evaluate("claude", "herdr:claude")
        assert c.eligible is False
        assert c.status is AdapterConformanceStatus.MISSING
        assert c.diagnostic, "MISSING must carry a diagnostic"

    def test_unavailable_rejects_with_diagnostic(self, gate_factory):
        gate = gate_factory({"codex": AdapterConformanceStatus.UNAVAILABLE})
        c = gate.evaluate("kimi", "herdr:codex")
        assert c.eligible is False
        assert c.status is AdapterConformanceStatus.UNAVAILABLE
        assert c.diagnostic, "UNAVAILABLE must carry a diagnostic"


class TestConformanceGateRegistry:
    def test_unknown_principal_missing(self, gate_factory):
        gate = gate_factory({"claude": AdapterConformanceStatus.HEALTHY})
        c = gate.evaluate("nobody", "herdr:claude")
        assert c.eligible is False
        assert c.status is AdapterConformanceStatus.MISSING
        assert any("not registered" in d for d in c.diagnostic)

    def test_unknown_execution_profile_missing(self, gate_factory):
        gate = gate_factory({"claude": AdapterConformanceStatus.HEALTHY})
        c = gate.evaluate("claude", "herdr:not-a-profile")
        assert c.eligible is False
        assert c.status is AdapterConformanceStatus.MISSING
        assert any("not in registry" in d for d in c.diagnostic)

    def test_principal_not_assigned_profile_missing(self, gate_factory):
        gate = gate_factory({"claude": AdapterConformanceStatus.HEALTHY})
        # qwen owns herdr:cline; herdr:claude is not assigned
        c = gate.evaluate("qwen", "herdr:claude")
        assert c.eligible is False
        assert c.status is AdapterConformanceStatus.MISSING
        assert any("not assigned" in d for d in c.diagnostic)

    def test_profile_without_herdr_kind_missing(self, gate_factory):
        gate = gate_factory({})
        # remote:mcp:chatgpt has no herdr_agent_kind -> not locally dispatchable
        c = gate.evaluate("chatgpt", "remote:mcp:chatgpt")
        assert c.eligible is False
        assert c.status is AdapterConformanceStatus.MISSING
        assert any("herdr_agent_kind" in d for d in c.diagnostic)

    def test_default_probe_is_missing(self, profiles):
        # Without a live detector, APCB never assumes an adapter exists.
        gate = ConformanceGate(profiles)
        c = gate.evaluate("claude", "herdr:claude")
        assert c.eligible is False
        assert c.status is AdapterConformanceStatus.MISSING


class TestConformanceSummary:
    def test_summary_bounded(self, gate_factory):
        gate = gate_factory({"opencode": AdapterConformanceStatus.EXPIRED})
        c = gate.evaluate("opencode", "herdr:opencode")
        s = c.summary()
        assert "opencode" in s
        assert "expired" in s
