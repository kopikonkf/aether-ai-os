"""Executable validation for the founder-supplied bootstrap sequence."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


EXPECTED_SEQUENCE = [
    "empty_state",
    "first_experience",
    "pattern_formation",
    "concept_formation",
    "belief_proposal",
    "prediction",
    "outcome_validation",
    "honest_audit",
]


@dataclass(frozen=True)
class BootstrapValidation:
    passed: bool
    errors: tuple[str, ...]
    policy: dict[str, Any]


def load_bootstrap_policy(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("bootstrap policy must be a mapping")
    return data


def validate_bootstrap_policy(path: Path) -> BootstrapValidation:
    policy = load_bootstrap_policy(path)
    errors: list[str] = []

    authority = policy.get("authority", {})
    if authority.get("north_star") != "src/aether/dna/north_star.yaml":
        errors.append("north_star must point to the sole DNA authority")
    if authority.get("duplicate_north_star") != "forbidden":
        errors.append("duplicate Northstar must be forbidden")
    if policy.get("sequence") != EXPECTED_SEQUENCE:
        errors.append("bootstrap learning sequence does not match the governed order")

    belief = policy.get("state_requirements", {}).get("belief_proposal", {})
    if belief.get("direct_conversation_to_belief") != "forbidden":
        errors.append("direct conversation-to-belief promotion must be forbidden")
    if belief.get("provenance_required") is not True:
        errors.append("belief provenance must be required")

    forbidden = set(policy.get("forbidden", []))
    required_forbidden = {
        "seed_mass_beliefs_on_first_boot",
        "inflate_confidence",
        "measure_growth_by_lines_of_code",
        "confuse_storage_with_knowledge",
    }
    missing = sorted(required_forbidden - forbidden)
    if missing:
        errors.append(f"missing forbidden bootstrap practices: {', '.join(missing)}")

    return BootstrapValidation(not errors, tuple(errors), policy)
