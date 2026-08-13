"""APCB conformance gate — hard gate before any Herdr dispatch.

Contract reference: project-docs/architecture/APCB_V0_1_IMPLEMENTATION_CONTRACT.md
Section 8 (Herdr adapter boundary). Chief-architect verdict (2026-08-12):

    detect adapter -> identify principal/runtime profile -> check conformance
      HEALTHY/VALID -> eligible (dispatch)
      EXPIRED       -> reject dispatch + diagnostic
      MISSING       -> reject dispatch + diagnostic
      unavailable   -> reject dispatch + diagnostic

There is NO forced fallback: when conformance fails, the gate must reject
with a diagnostic instead of silently falling back to a shell/terminal path
that was never checked.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable, Mapping

from aether.apcb.profiles import ExecutionProfile, PrincipalRuntimeProfiles


class AdapterConformanceStatus(StrEnum):
    HEALTHY = "healthy"
    VALID = "valid"
    EXPIRED = "expired"
    MISSING = "missing"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class AdapterConformance:
    """Result of the conformance gate for one principal + execution profile.

    `eligible` is True only for HEALTHY/VALID. Everything else rejects the
    dispatch and carries a bounded diagnostic.
    """

    principal_id: str
    execution_profile: str | None
    herdr_agent_kind: str | None
    status: AdapterConformanceStatus
    diagnostic: tuple[str, ...] = field(default_factory=tuple)
    details: Mapping[str, Any] = field(default_factory=dict)

    @property
    def eligible(self) -> bool:
        return self.status in (AdapterConformanceStatus.HEALTHY, AdapterConformanceStatus.VALID)

    def summary(self) -> str:
        base = f"{self.principal_id}:{self.execution_profile or '-'} -> {self.status.value}"
        if self.diagnostic:
            return f"{base} ({'; '.join(self.diagnostic)})"
        return base


AgentKindProbe = Callable[[str], AdapterConformanceStatus]


def _default_probe(agent_kind: str) -> AdapterConformanceStatus:
    """Default probe: without a live detector every kind is 'missing'.

    A real detector (Herdr CLI capability detection) is wired by the caller.
    APCB never assumes an adapter is present just because a profile names it.
    """
    return AdapterConformanceStatus.MISSING


class ConformanceGate:
    """Evaluate whether a principal's execution profile is conformant for dispatch.

    Steps (chief-architect verdict):
      1. detect adapter  -> probe the herdr agent kind
      2. identify principal/runtime profile -> registry lookup
      3. check conformance -> eligible / reject + diagnostic

    The gate is injectable with an `AgentKindProbe` for deterministic tests.
    """

    def __init__(
        self,
        profiles: PrincipalRuntimeProfiles,
        probe: AgentKindProbe | None = None,
    ) -> None:
        self.profiles = profiles
        self.probe = probe or _default_probe

    def evaluate(self, principal_id: str, execution_profile: str) -> AdapterConformance:
        profile = self.profiles.get_principal(principal_id)
        if profile is None:
            return AdapterConformance(
                principal_id=principal_id,
                execution_profile=execution_profile,
                herdr_agent_kind=None,
                status=AdapterConformanceStatus.MISSING,
                diagnostic=("principal not registered in principal_runtime_profiles",),
            )

        ep = self.profiles.get_execution_profile(execution_profile)
        if ep is None:
            return AdapterConformance(
                principal_id=principal_id,
                execution_profile=execution_profile,
                herdr_agent_kind=None,
                status=AdapterConformanceStatus.MISSING,
                diagnostic=(f"execution profile '{execution_profile}' not in registry",),
            )

        if execution_profile not in profile.execution_profiles:
            return AdapterConformance(
                principal_id=principal_id,
                execution_profile=execution_profile,
                herdr_agent_kind=ep.herdr_agent_kind,
                status=AdapterConformanceStatus.MISSING,
                diagnostic=(
                    f"principal '{principal_id}' is not assigned execution profile '{execution_profile}'",
                ),
            )

        return self._evaluate_adapter(principal_id, ep)

    def _evaluate_adapter(self, principal_id: str, ep: ExecutionProfile) -> AdapterConformance:
        agent_kind = ep.herdr_agent_kind
        if not agent_kind:
            return AdapterConformance(
                principal_id=principal_id,
                execution_profile=ep.name,
                herdr_agent_kind=None,
                status=AdapterConformanceStatus.MISSING,
                diagnostic=(
                    f"execution profile '{ep.name}' has no herdr_agent_kind binding; "
                    "only herdr:* profiles are dispatchable via APCB",
                ),
            )

        status = self.probe(agent_kind)
        if status in (AdapterConformanceStatus.HEALTHY, AdapterConformanceStatus.VALID):
            return AdapterConformance(
                principal_id=principal_id,
                execution_profile=ep.name,
                herdr_agent_kind=agent_kind,
                status=status,
                diagnostic=(),
            )

        reason = {
            AdapterConformanceStatus.EXPIRED: "adapter probe reports EXPIRED (reliability/penalty)",
            AdapterConformanceStatus.MISSING: f"adapter for agent kind '{agent_kind}' is MISSING",
            AdapterConformanceStatus.UNAVAILABLE: f"adapter for agent kind '{agent_kind}' is UNAVAILABLE",
        }.get(status, "adapter conformance check failed")

        return AdapterConformance(
            principal_id=principal_id,
            execution_profile=ep.name,
            herdr_agent_kind=agent_kind,
            status=status,
            diagnostic=(reason,),
        )

    def eligible(self, conformance: AdapterConformance) -> bool:
        return conformance.eligible
