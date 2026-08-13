"""Deterministic mapping-invariant tests for the agnostic fleet (Gate 3, WORK-3).

Enforces, read-only from the Aether-owned config
(aether-core/configs/principal_runtime_profiles.v0.yaml), the 4-field invariant:

    principal_id != execution_profile != herdr_agent_kind != model_provider

Background findings encoded here (referenced, not copied):
  - WORK-1 F1 / C1: ``model_provider`` is NOT a structured YAML field (only
    free-text ``note:``), so the 4th dimension cannot be machine-read from the
    config alone. This suite (a) enforces the three config-readable dimensions
    deterministically, (b) pins the canonical `model_provider` mapping as an
    explicit deterministic fixture so the FULL invariant is enforced end-to-end,
    and (c) provides a forward-compatible structured-fuel validator that becomes
    the source of truth the moment a structured ``model_provider``/``fuel`` field
    is added to the YAML.
  - WORK-2 G1: a pane-collision guard asserts exactly one pane per sovereign
    principal. It is EXPECTED to stay RED until COORD fixes apcb_pane_map.json
    (do not merge while RED).
  - Mock herdr: no live herdr/agent calls. Pure config + JSON file reads only.

NON-ACTIVATION: read-only over config; no repo mutation, no dispatch.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml

from aether.apcb import load_principal_profiles
from aether.apcb.profiles import PrincipalRuntimeProfiles

# ---------------------------------------------------------------------------
# Canonical mapping (WORK-1 / packet section 2). opencode is an
# integration_runtime_coordinator and is explicitly excluded from the sovereign
# set; the 6 sovereign principals below carry the invariant.
# ---------------------------------------------------------------------------
SOVEREIGN = ("claude", "gemini", "qwen", "kimi", "chatgpt", "deepseek")

CANONICAL_PROFILE = {
    "claude": "herdr:freebuff",
    "gemini": "herdr:claude",
    "qwen": "herdr:cline",
    "kimi": "herdr:codex",
    "chatgpt": "herdr:opencode",
    "deepseek": "herdr:kilo",
}

# Canonical fuel (model_provider) per sovereign principal. Not a structured
# config field (F1), so pinned here as the deterministic 4th dimension until a
# structured fuel field is added to the YAML.
FUEL_BY_PRINCIPAL = {
    "claude": "deepseek-v4-flash",
    "gemini": "kimi",
    "qwen": "deepseek-v4-flash",
    "kimi": "gpt-5.5",
    "chatgpt": "deepseek-v4-flash",
    "deepseek": "deepseek-v4-flash",
}

_FUEL_FIELD_NAMES = ("model_provider", "fuel")


# ---------------------------------------------------------------------------
# Invariant helpers (pure, deterministic)
# ---------------------------------------------------------------------------
def _four_fields(
    principal_id: str, profile_name: str, herdr_agent_kind: str, model_provider: str
) -> list[str]:
    fields = [principal_id, profile_name, herdr_agent_kind, model_provider]
    assert all(f and f.strip() for f in fields), f"empty invariant field: {fields}"
    return fields


def _assert_invariant_distinct(fields: list[str]) -> None:
    assert len(set(fields)) == len(fields), (
        f"invariant violated: not pairwise-distinct -> {fields}"
    )


def _registry() -> PrincipalRuntimeProfiles:
    return load_principal_profiles()


def _resolve_herdr_kind(reg: PrincipalRuntimeProfiles, principal_id: str) -> str:
    """Config-sourced herdr_agent_kind for a principal's canonical profile."""
    profile_name = CANONICAL_PROFILE[principal_id]
    principal = reg.get_principal(principal_id)
    assert principal is not None, f"principal {principal_id} missing from registry"
    assert profile_name in principal.execution_profiles, (
        f"{principal_id} must be assigned {profile_name}"
    )
    ep = reg.get_execution_profile(profile_name)
    assert ep is not None, f"execution profile {profile_name} missing from registry"
    assert ep.herdr_agent_kind, f"{profile_name} has no herdr_agent_kind"
    return ep.herdr_agent_kind


def _structured_fuel_map() -> dict[str, dict]:
    """Return any structured ``model_provider``/``fuel`` field found on the
    sovereign principals (read-only YAML re-parse). Empty == F1 still holds."""
    repo_root = Path(__file__).resolve().parents[3]
    cfg = repo_root / "aether-core" / "configs" / "principal_runtime_profiles.v0.yaml"
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    principals = data.get("principals") or {}
    out: dict[str, dict] = {}
    for pid, entry in principals.items():
        for key in _FUEL_FIELD_NAMES:
            if key in entry:
                out[pid] = {"key": key, "value": entry[key]}
                break
    return out


def _pane_map() -> dict:
    path = os.environ.get("APCB_HERDR_PANE_MAP") or r"D:\aether-bridge\apcb_pane_map.json"
    p = Path(path)
    if not p.exists():
        pytest.skip(f"pane map not found: {p}")
    return json.loads(p.read_text(encoding="utf-8")).get("panes", {})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_sovereign_set_and_exclusion():
    reg = _registry()
    for pid in SOVEREIGN:
        assert pid in reg.principals, f"sovereign principal {pid} not in registry"
    # opencode is an integration_runtime_coordinator, not a sovereign principal
    # (its execution profile uses work_mode=integration; WORK-1 section 2).
    opencode = reg.get_principal("opencode")
    assert opencode is not None
    assert opencode.id not in SOVEREIGN
    assert "integration" in opencode.role


def test_canonical_profile_assigned_to_sovereign():
    reg = _registry()
    for pid in SOVEREIGN:
        principal = reg.get_principal(pid)
        assert principal is not None
        assert CANONICAL_PROFILE[pid] in principal.execution_profiles, (
            f"{pid} must be assigned its canonical {CANONICAL_PROFILE[pid]}"
        )


def test_three_structured_fields_distinct_from_config():
    """principal_id != execution_profile != herdr_agent_kind — all sourced from
    the config registry (no fixture for these three)."""
    reg = _registry()
    for pid in SOVEREIGN:
        profile_name = CANONICAL_PROFILE[pid]
        herdr_kind = _resolve_herdr_kind(reg, pid)
        fields = [pid, profile_name, herdr_kind]
        assert len(set(fields)) == len(fields), (
            f"structured-field invariant violated for {pid}: {fields}"
        )


def test_four_field_invariant_with_fuel_fixture():
    """Full invariant including the 4th dimension (model_provider), where the
    fuel is pinned by fixture because it is not (yet) a structured config field."""
    reg = _registry()
    for pid in SOVEREIGN:
        profile_name = CANONICAL_PROFILE[pid]
        herdr_kind = _resolve_herdr_kind(reg, pid)
        model_provider = FUEL_BY_PRINCIPAL[pid]
        _assert_invariant_distinct(_four_fields(pid, profile_name, herdr_kind, model_provider))


def test_fuel_and_profile_fixtures_cover_all_sovereign():
    assert set(FUEL_BY_PRINCIPAL) == set(SOVEREIGN)
    assert set(CANONICAL_PROFILE) == set(SOVEREIGN)
    # All four dimensions present per row (no accidental None/empty fuel).
    for pid in SOVEREIGN:
        assert FUEL_BY_PRINCIPAL[pid].strip()


def test_structured_fuel_not_yet_present_documents_f1():
    """F1: model_provider/fuel are NOT structured config fields today. When a
    structured fuel field is added, this assertion fails and signals that
    FUEL_BY_PRINCIPAL should be replaced by the config-sourced value."""
    structured = _structured_fuel_map()
    assert structured == {}, (
        "structured fuel field detected in config; update this test and "
        f"FUEL_BY_PRINCIPAL to source the 4th dimension from config (resolves F1): {structured}"
    )


def test_structured_fuel_validator_forward_compatible():
    """Forward-compatible validator: a structured fuel value must not re-use the
    principal_id, execution_profile, or herdr_agent_kind of its row."""
    _assert_invariant_distinct(_four_fields("qwen", "herdr:cline", "cline", "deepseek-v4-flash"))
    _assert_invariant_distinct(_four_fields("gemini", "herdr:claude", "claude", "kimi"))
    with pytest.raises(AssertionError):
        # fuel collides with herdr_agent_kind -> must be rejected
        _assert_invariant_distinct(_four_fields("qwen", "herdr:cline", "cline", "cline"))
    with pytest.raises(AssertionError):
        # fuel collides with principal_id -> must be rejected
        _assert_invariant_distinct(_four_fields("qwen", "herdr:cline", "cline", "qwen"))


def test_sovereign_panes_are_unique():
    """WORK-2 G1 guard: exactly one pane per sovereign principal.

    NOTE: currently EXPECTED to FAIL because apcb_pane_map.json maps both gemini
    and qwen to w7:p4 (no w7:p5). COORD must resolve the pane map; once fixed
    this test goes green. Do not merge while RED.
    """
    panes = _pane_map()
    missing = [pid for pid in SOVEREIGN if pid not in panes]
    assert not missing, f"pane map missing sovereign principals: {missing}"
    seen: dict[str, str] = {}
    for pid in SOVEREIGN:
        pane = panes[pid]
        assert pane and pane.strip(), f"{pid} mapped to empty pane"
        assert pane not in seen, (
            f"pane collision: {seen[pane]} and {pid} both map to {pane}"
        )
        seen[pane] = pid

