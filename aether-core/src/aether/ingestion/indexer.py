from __future__ import annotations

from pathlib import Path
from typing import Any

from aether.ingestion.workspace import ensure_ingestion_workspace, manifest_path
from aether.utils.jsonio import read_jsonl, write_json
from aether.obsidian import build_vault_index
from aether.utils.time import utc_now


def build_ingestion_index(root: Path, write: bool = True) -> dict[str, Any]:
    ensure_ingestion_workspace(root)
    rows = read_jsonl(manifest_path(root))
    sources = []
    claims = []
    for row in rows:
        source = row.get("source", {})
        if source:
            sources.append(source)
        claims.extend(row.get("claims", []))

    by_type: dict[str, int] = {}
    for source in sources:
        source_type = source.get("source_type", "unknown")
        by_type[source_type] = by_type.get(source_type, 0) + 1

    index = {
        "generated_at": utc_now(),
        "source_count": len(sources),
        "claim_count": len(claims),
        "sources_by_type": by_type,
        "sources": sources,
        "claims": claims,
    }
    if write:
        write_json(root / "runtime_state" / "ingestion" / "index.json", index)
        write_json(root / "runtime_state" / "ingestion" / "indexes" / "sources.json", sources)
        write_json(root / "runtime_state" / "ingestion" / "indexes" / "claims.json", claims)
        md = _index_md(index)
        target = root / "obsidian" / "vault" / "00_System" / "indexes" / "Ingestion_Index.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(md, encoding="utf-8")
        write_json(root / "runtime_state" / "reports" / "ingestion_index_latest.json", index)
        build_vault_index(root, write=True)
    return index


def _index_md(index: dict[str, Any]) -> str:
    lines = [
        "# Ingestion Index",
        "",
        f"Generated: {index['generated_at']}",
        f"Sources: {index['source_count']}",
        f"Claims: {index['claim_count']}",
        "",
        "## Sources by Type",
    ]
    for source_type, count in sorted(index["sources_by_type"].items()):
        lines.append(f"- {source_type}: {count}")
    lines.extend(["", "## Latest Sources"])
    for source in index["sources"][-25:]:
        lines.append(f"- `{source.get('source_id')}` — {source.get('title')} — {source.get('source_type')} — trust {source.get('trust_score')}")
    return "\n".join(lines) + "\n"


def ingestion_status(root: Path) -> dict[str, Any]:
    ensure_ingestion_workspace(root)
    index = build_ingestion_index(root, write=True)
    inbox = root / "ingestion" / "inbox"
    pending = [p.name for p in inbox.iterdir() if p.is_file() and p.name != "README.md"]
    jobs_dir = root / "runtime_state" / "ingestion" / "jobs"
    queued_jobs = [p.name for p in jobs_dir.glob("*.json")]
    return {
        "ok": True,
        "source_count": index["source_count"],
        "claim_count": index["claim_count"],
        "pending_inbox_count": len(pending),
        "pending_inbox_files": pending,
        "queued_external_fetch_count": len(queued_jobs),
        "queued_external_fetch_jobs": queued_jobs,
        "manifest_exists": manifest_path(root).exists(),
        "index_exists": (root / "runtime_state" / "ingestion" / "index.json").exists(),
    }


def validate_ingestion_workspace(root: Path) -> dict[str, Any]:
    status = ingestion_status(root)
    errors = []
    required = [
        root / "ingestion" / "inbox",
        root / "runtime_state" / "ingestion",
        root / "runtime_state" / "ingestion" / "archive",
        root / "obsidian" / "vault" / "03_Sources",
        root / "obsidian" / "vault" / "04_Digests",
        root / "obsidian" / "vault" / "00_System" / "indexes",
    ]
    for path in required:
        if not path.exists():
            errors.append(f"missing: {path.relative_to(root).as_posix()}")
    status["errors"] = errors
    status["ok"] = not errors
    write_json(root / "runtime_state" / "reports" / "ingestion_validation_latest.json", status)
    return status
