from __future__ import annotations

from pathlib import Path
from typing import Any

from aether.utils.jsonio import read_json, read_jsonl, write_json
from aether.obsidian import build_vault_index, ensure_vault
from aether.utils.time import utc_now
from aether.knowledge.workspace import (
    ensure_knowledge_workspace,
    registry_path,
    review_decisions_path,
    evidence_links_path,
    promotions_path,
    knowledge_index_path,
)


def _count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key, "unknown"))
        result[value] = result.get(value, 0) + 1
    return result


def build_knowledge_index(root: Path, write: bool = True) -> dict[str, Any]:
    ensure_knowledge_workspace(root)
    ensure_vault(root)
    claims = read_json(registry_path(root), default=[])
    reviews = read_jsonl(review_decisions_path(root))
    evidence = read_jsonl(evidence_links_path(root))
    promotions = read_jsonl(promotions_path(root))
    index = {
        "generated_at": utc_now(),
        "claim_count": len(claims),
        "review_count": len(reviews),
        "evidence_count": len(evidence),
        "promotion_count": len(promotions),
        "claims_by_status": _count_by(claims, "status"),
        "claims_by_maturity": _count_by(claims, "maturity"),
        "contradiction_status": _count_by(claims, "contradiction_status"),
        "latest_claims": claims[-25:],
        "latest_promotions": promotions[-25:],
    }
    if write:
        write_json(knowledge_index_path(root), index)
        write_json(root / "runtime_state" / "knowledge" / "indexes" / "claims_by_status.json", index["claims_by_status"])
        write_json(root / "runtime_state" / "knowledge" / "indexes" / "claims_by_maturity.json", index["claims_by_maturity"])
        target = root / "obsidian" / "vault" / "00_System" / "indexes" / "Knowledge_Lifecycle_Index.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_index_md(index), encoding="utf-8")
        write_json(root / "runtime_state" / "reports" / "knowledge_lifecycle_index_latest.json", index)
        build_vault_index(root, write=True)
    return index


def _index_md(index: dict[str, Any]) -> str:
    lines = [
        "# Knowledge Lifecycle Index",
        "",
        f"Generated: {index['generated_at']}",
        f"Claims: {index['claim_count']}",
        f"Reviews: {index['review_count']}",
        f"Evidence Links: {index['evidence_count']}",
        f"Promotions: {index['promotion_count']}",
        "",
        "## Claims by Status",
    ]
    for status, count in sorted(index["claims_by_status"].items()):
        lines.append(f"- {status}: {count}")
    lines.extend(["", "## Claims by Maturity"])
    for maturity, count in sorted(index["claims_by_maturity"].items()):
        lines.append(f"- {maturity}: {count}")
    lines.extend(["", "## Latest Claims"])
    for claim in index["latest_claims"]:
        lines.append(f"- `{claim.get('lifecycle_claim_id')}` — {claim.get('status')} / {claim.get('maturity')} — {claim.get('claim')}")
    lines.extend(["", "## Latest Promotions"])
    for promotion in index["latest_promotions"]:
        lines.append(f"- `{promotion.get('promotion_id')}` — {promotion.get('target')} — {promotion.get('note_path')}")
    return "\n".join(lines) + "\n"


def knowledge_status(root: Path) -> dict[str, Any]:
    ensure_knowledge_workspace(root)
    index = build_knowledge_index(root, write=True)
    return {
        "ok": True,
        "claim_count": index["claim_count"],
        "review_count": index["review_count"],
        "evidence_count": index["evidence_count"],
        "promotion_count": index["promotion_count"],
        "claims_by_status": index["claims_by_status"],
        "claims_by_maturity": index["claims_by_maturity"],
        "index_exists": knowledge_index_path(root).exists(),
    }


def validate_knowledge_workspace(root: Path) -> dict[str, Any]:
    status = knowledge_status(root)
    errors: list[str] = []
    required = [
        root / "runtime_state" / "knowledge",
        root / "runtime_state" / "knowledge" / "claim_registry.json",
        root / "runtime_state" / "knowledge" / "index.json",
        root / "obsidian" / "vault" / "05_Knowledge",
        root / "obsidian" / "vault" / "06_Beliefs",
        root / "obsidian" / "vault" / "00_System" / "indexes" / "Knowledge_Lifecycle_Index.md",
    ]
    for path in required:
        if not path.exists():
            errors.append(f"missing: {path.relative_to(root).as_posix()}")
    status["errors"] = errors
    status["ok"] = not errors
    return status
