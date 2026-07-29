"""Validate active Aether Memory Fabric invariants without starting a runtime."""
from __future__ import annotations

from pathlib import Path
import sys
import yaml


def validate(repo_root: Path) -> list[str]:
    errors: list[str] = []
    config_path = repo_root / "configs" / "memory_fabric.yaml"
    packaged_path = repo_root / "src" / "aether" / "memory" / "memory_fabric.yaml"
    if not config_path.exists() or not packaged_path.exists():
        return ["memory fabric config or packaged policy is missing"]
    if config_path.read_text(encoding="utf-8") != packaged_path.read_text(encoding="utf-8"):
        errors.append("operator and packaged memory policies diverged")

    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if config.get("status") != "active":
        errors.append("memory fabric must be active")
    ownership = config.get("ownership", {})
    if ownership.get("canonical_authority") != "aether_core":
        errors.append("canonical episode authority must remain Aether Core")
    if ownership.get("identity_authority") != "aether_dna":
        errors.append("identity authority must remain Aether DNA")

    operational = config.get("operational", {})
    canonical = operational.get("canonical_episodic_store", {})
    if canonical.get("append_only") is not True:
        errors.append("canonical episodic store must be append-only")
    if canonical.get("direct_knowledge_promotion") != "forbidden":
        errors.append("episodes must not directly become knowledge")
    if canonical.get("direct_belief_promotion") != "forbidden":
        errors.append("episodes must not directly become beliefs")
    proposals = operational.get("knowledge_proposal_store", {})
    if proposals.get("proposal_records_immutable") is not True:
        errors.append("knowledge proposals must be immutable")
    if proposals.get("evidence_records_immutable") is not True:
        errors.append("knowledge evidence must be immutable")
    if proposals.get("decision_records_immutable") is not True:
        errors.append("knowledge decisions must be immutable")
    retrieval = operational.get("retrieval_projection", {})
    if retrieval.get("rebuildable") is not True:
        errors.append("retrieval projection must be rebuildable")
    obsidian = operational.get("obsidian_projection", {})
    if obsidian.get("authority") != "projection_only":
        errors.append("Obsidian must remain projection-only")

    curation = config.get("curation", {})
    if curation.get("explicit_candidate_metadata_only") is not True:
        errors.append("automatic curation must require explicit candidate metadata")
    if curation.get("duplicate_detection") != "required":
        errors.append("duplicate detection must be required")
    if curation.get("contradiction_detection") != "required":
        errors.append("contradiction detection must be required")
    if curation.get("trusted_terminal_decision_required") is not True:
        errors.append("knowledge promotion requires trusted terminal governance")
    if curation.get("automatic_belief_promotion") != "forbidden":
        errors.append("automatic belief promotion must remain forbidden")

    recall = config.get("retrieval", {})
    if recall.get("before_cognition") is not True:
        errors.append("retrieval must occur before cognition")
    if recall.get("require_provenance") is not True:
        errors.append("retrieved context must preserve provenance")

    install = config.get("installation_policy", {})
    if install.get("install_all_evaluated_providers") is not False:
        errors.append("providers must be installed on demand")
    if install.get("core_external_memory_dependencies") != []:
        errors.append("native MVP must not require external memory dependencies")

    text = config_path.read_text(encoding="utf-8").lower()
    prohibited = "her" + "mes"
    if prohibited in text:
        errors.append("legacy runtime identity leaked into memory policy")
    return errors


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    errors = validate(repo_root)
    if errors:
        print("MEMORY FABRIC: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("MEMORY FABRIC: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
