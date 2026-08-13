"""APCB principal profile registry loader (Aether-owned configuration).

Contract reference: project-docs/architecture/APCB_V0_1_IMPLEMENTATION_CONTRACT.md
Section 7 (principal profile registry) + aether-core/configs/principal_runtime_profiles.v0.yaml.

Invariants:
  - principal_id is identity/attribution, not authorization;
  - role never implies mutation authority;
  - execution profile maps to a known Herdr integration or a controlled
    compatible-agent profile; never arbitrary shell text;
  - mutation authority remains governed by Aether policy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# Relative to repo root (aether-core/configs/...)
_DEFAULT_REGISTRY_REL = Path("aether-core/configs/principal_runtime_profiles.v0.yaml")


@dataclass(frozen=True)
class ExecutionProfile:
    name: str
    herdr_agent_kind: str | None = None
    transport: str | None = None
    work_mode: str = "task"
    direct_handoff: bool = False
    availability: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PrincipalProfile:
    id: str
    role: str
    capabilities: frozenset[str]
    execution_profiles: tuple[str, ...]
    mutation_authority: bool
    note: str | None = None
    model_provider: str | None = None

    def has_capability(self, capability: str) -> bool:
        return capability in self.capabilities


class PrincipalRuntimeProfiles:
    """In-memory registry of principal runtime profiles.

    Loaded once from the Founder-owned YAML registry. Fail-closed on invalid
    shape: a malformed registry must raise, never silently produce an empty or
    partial profile set.
    """

    def __init__(self, registry_path: Path | None = None) -> None:
        self._path = registry_path or self._default_path()
        if not self._path.exists():
            raise FileNotFoundError(f"APCB principal profile registry not found: {self._path}")
        self._data = self._load_yaml(self._path)
        self.principals: dict[str, PrincipalProfile] = {}
        self.execution_profiles: dict[str, ExecutionProfile] = {}
        self.routing: dict[str, list[str]] = {}
        self.handoff_protocol: str = "aether-canonical-artifact"
        self.dispatch_idempotency_key: tuple[str, str, str, str] = (
            "mission_id",
            "work_id",
            "attempt_number",
            "principal_id",
        )
        self._parse(self._data)

    # ------------------------------------------------------------------
    @staticmethod
    def _default_path() -> Path:
        # aether-core/src/aether/apcb/profiles.py -> repo root
        here = Path(__file__).resolve()
        repo_root = here.parents[4]
        return repo_root / _DEFAULT_REGISTRY_REL

    @staticmethod
    def _load_yaml(path: Path) -> dict[str, Any]:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ValueError(f"APCB profile registry must be a mapping: {path}")
        return data

    # ------------------------------------------------------------------
    def _parse(self, data: dict[str, Any]) -> None:
        defaults = data.get("defaults", {})
        default_mutation = bool(defaults.get("mutation_authority", False))

        principals_raw = data.get("principals")
        if not isinstance(principals_raw, dict):
            raise ValueError("principal_runtime_profiles: 'principals' must be a mapping")

        for pid, entry in principals_raw.items():
            if not isinstance(entry, dict):
                raise ValueError(f"principal '{pid}' entry must be a mapping")
            caps = entry.get("capabilities", [])
            if not isinstance(caps, list):
                raise ValueError(f"principal '{pid}'.capabilities must be a list")
            profiles = entry.get("execution_profiles", [])
            if not isinstance(profiles, list):
                raise ValueError(f"principal '{pid}'.execution_profiles must be a list")
            self.principals[pid] = PrincipalProfile(
                id=pid,
                role=entry.get("role", "worker"),
                capabilities=frozenset(str(c) for c in caps),
                execution_profiles=tuple(str(p) for p in profiles),
                mutation_authority=bool(entry.get("mutation_authority", default_mutation)),
                note=entry.get("note"),
                model_provider=entry.get("model_provider"),
            )

        profiles_raw = data.get("execution_profiles")
        if not isinstance(profiles_raw, dict):
            raise ValueError("principal_runtime_profiles: 'execution_profiles' must be a mapping")

        for name, entry in profiles_raw.items():
            if not isinstance(entry, dict):
                raise ValueError(f"execution profile '{name}' entry must be a mapping")
            self.execution_profiles[name] = ExecutionProfile(
                name=name,
                herdr_agent_kind=entry.get("herdr_agent_kind"),
                transport=entry.get("transport"),
                work_mode=entry.get("work_mode", "task"),
                direct_handoff=bool(entry.get("direct_handoff", False)),
                availability=entry.get("availability"),
                raw=entry,
            )

        routing = data.get("routing", {})
        if isinstance(routing, dict):
            self.routing = {k: list(v) for k, v in routing.items()}

        if isinstance(data.get("handoff"), dict):
            self.handoff_protocol = data["handoff"].get("protocol", self.handoff_protocol)

        if isinstance(data.get("herdr"), dict) and isinstance(
            data["herdr"].get("dispatch_idempotency_key"), list
        ):
            self.dispatch_idempotency_key = tuple(data["herdr"]["dispatch_idempotency_key"])

    # ------------------------------------------------------------------
    def get_principal(self, principal_id: str) -> PrincipalProfile | None:
        return self.principals.get(principal_id)

    def get_execution_profile(self, name: str) -> ExecutionProfile | None:
        return self.execution_profiles.get(name)

    def principal_can(self, principal_id: str, capability: str) -> bool:
        p = self.principals.get(principal_id)
        return bool(p and p.has_capability(capability))

    def principal_has_profile(self, principal_id: str, profile_name: str) -> bool:
        p = self.principals.get(principal_id)
        return bool(p and profile_name in p.execution_profiles)


def load_principal_profiles(
    registry_path: Path | None = None,
) -> PrincipalRuntimeProfiles:
    return PrincipalRuntimeProfiles(registry_path)
