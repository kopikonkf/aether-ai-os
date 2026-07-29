"""Obsidian projection for governed, promoted knowledge."""
from __future__ import annotations

import re
from pathlib import Path

from aether.contracts.knowledge import KnowledgeDecision, KnowledgeProposal
from aether.contracts.memory import MemoryRecord
from aether.utils.time import utc_now


def _slug(text: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", text.strip()).strip("-").lower()
    return value or "knowledge"


def _yaml_escape(text: str) -> str:
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"') + '"'


class ObsidianKnowledgeProjector:
    projector_id = "aether.knowledge.obsidian-projection"

    def __init__(self, vault_root: Path) -> None:
        self.vault_root = vault_root
        self.target = vault_root / "05_Knowledge" / "Aether Curated"
        self.target.mkdir(parents=True, exist_ok=True)

    async def project(
        self,
        proposal: KnowledgeProposal,
        decision: KnowledgeDecision,
        record: MemoryRecord,
    ) -> Path:
        path = self.target / f"{_slug(proposal.claim_key)}-{proposal.proposal_id[-8:]}.md"
        lines = [
            "---",
            f"title: {_yaml_escape(proposal.claim)}",
            "type: governed_knowledge",
            "authority: projection_only",
            f"proposal_id: {_yaml_escape(proposal.proposal_id)}",
            f"knowledge_record_id: {_yaml_escape(record.record_id or '')}",
            f"decision_id: {_yaml_escape(decision.decision_id)}",
            f"confidence: {decision.confidence if decision.confidence is not None else 'null'}",
            f"projected_at: {_yaml_escape(utc_now())}",
            "---",
            "",
            f"# {proposal.claim}",
            "",
            "> This note is rebuildable. Canonical authority remains in Aether's knowledge memory.",
            "",
            "## Governance decision",
            "",
            f"- Principal: `{decision.principal}`",
            f"- Channel: `{decision.channel}`",
            f"- Reason: {decision.reason}",
            f"- Decided at: `{decision.decided_at}`",
            "",
            "## Evidence bundle",
            "",
        ]
        for evidence in proposal.evidence:
            lines.extend([
                f"### {evidence.stance.value.title()} — `{evidence.record_id}`",
                "",
                evidence.excerpt,
                "",
                f"- Source: `{evidence.source}`",
                f"- Observed: `{evidence.observed_at}`",
                f"- Content hash: `{evidence.content_hash}`",
                "",
            ])
        if proposal.contradiction_ids:
            lines.extend([
                "## Visible contradictions",
                "",
                *[f"- `{item}`" for item in proposal.contradiction_ids],
                "",
            ])
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return path
