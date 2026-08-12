"""Principal registry loader for Aether MCP OAuth Edge.

Loads and validates configs/principal_registry.yaml — the Founder-owned policy
document that declares which AI principals may connect and what scopes they hold.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


# Scopes defined in ADR-0056
VALID_SCOPES = frozenset({"aether.read", "aether.diagnostic", "aether.mutate"})


@dataclass(frozen=True)
class Principal:
    id: str
    display_name: str
    client_id: str
    allowed_scopes: frozenset[str]
    redirect_uris: frozenset[str]
    mutation_authority: bool

    def allows_scope(self, scope: str) -> bool:
        return scope in self.allowed_scopes

    def allows_redirect_uri(self, redirect_uri: str) -> bool:
        """Exact-match allowlist for the redirect_uri a client may present (P0 #6)."""
        return redirect_uri in self.redirect_uris

    def effective_scopes(self, requested: list[str]) -> list[str]:
        """Return intersection of requested scopes and allowed scopes.

        aether.mutate is additionally gated by mutation_authority.
        """
        result = []
        for s in requested:
            if s not in self.allowed_scopes:
                continue
            if s == "aether.mutate" and not self.mutation_authority:
                continue
            result.append(s)
        return result


class PrincipalRegistry:
    """In-memory registry loaded from principal_registry.yaml."""

    def __init__(self, registry_path: Optional[Path] = None) -> None:
        if registry_path is None:
            # Default: configs/principal_registry.yaml relative to repo root
            repo_root = Path(__file__).parent.parent.parent.parent.parent.parent
            registry_path = repo_root / "configs" / "principal_registry.yaml"
        self._path = registry_path
        self._by_id: dict[str, Principal] = {}
        self._by_client_id: dict[str, Principal] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            raise FileNotFoundError(
                f"Principal registry not found: {self._path}. "
                "Create configs/principal_registry.yaml (see ADR-0056)."
            )
        with open(self._path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        principals = data.get("principals", [])
        for entry in principals:
            redirect_uris = entry.get("redirect_uris", [])
            if not redirect_uris:
                raise ValueError(
                    f"principal '{entry.get('id')}' has no redirect_uris — "
                    "every principal must declare an exact redirect URI allowlist (P0 #6)."
                )
            p = Principal(
                id=entry["id"],
                display_name=entry["display_name"],
                client_id=entry["client_id"],
                allowed_scopes=frozenset(entry.get("allowed_scopes", [])),
                redirect_uris=frozenset(redirect_uris),
                mutation_authority=bool(entry.get("mutation_authority", False)),
            )
            self._by_id[p.id] = p
            self._by_client_id[p.client_id] = p

    def get_by_id(self, principal_id: str) -> Optional[Principal]:
        return self._by_id.get(principal_id)

    def get_by_client_id(self, client_id: str) -> Optional[Principal]:
        return self._by_client_id.get(client_id)

    def all(self) -> list[Principal]:
        return list(self._by_id.values())


# Module-level singleton — loaded once at import time
def _default_registry_path() -> Path:
    env_path = os.getenv("AETHER_PRINCIPAL_REGISTRY")
    if env_path:
        return Path(env_path)
    # __file__ = aether-gateway/src/aether_gateway/oauth_edge/registry.py
    # .parent * 5 = aether-ai-os/ (repo root)
    repo_root = Path(__file__).parent.parent.parent.parent.parent
    return repo_root / "configs" / "principal_registry.yaml"


_registry: Optional[PrincipalRegistry] = None


def get_registry() -> PrincipalRegistry:
    global _registry
    if _registry is None:
        _registry = PrincipalRegistry(_default_registry_path())
    return _registry
