from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

from aether.events import EventBus
from aether.utils.ids import new_id
from aether.ingestion.extractors import extract_claims, extract_text_from_file, summarize_text
from aether.ingestion.trust import trust_score
from aether.ingestion.workspace import archive_dir, ensure_ingestion_workspace, inbox_dir, manifest_path, processed_dir, rejected_dir
from aether.utils.jsonio import append_jsonl, write_json
from aether.ledger import AppendOnlyLedger
from aether.obsidian import build_vault_index, write_note, write_source_digest
from aether.paths import RuntimePaths
from aether.utils.time import utc_now


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_title(path: Path) -> str:
    return path.stem.replace("_", " ").replace("-", " ").strip() or "Untitled Source"


def _record_runtime(root: Path, result: dict[str, Any]) -> None:
    ensure_ingestion_workspace(root)
    append_jsonl(manifest_path(root), result)
    write_json(root / "runtime_state" / "ingestion" / "latest_result.json", result)


def _write_source_note(root: Path, source: dict[str, Any], summary: str, claims: list[str]) -> dict[str, Any]:
    claim_lines = "\n".join(f"- {claim}" for claim in claims) or "- No claims extracted."
    body = f"""# Source - {source['title']}

## Source Metadata

- Source ID: `{source['source_id']}`
- Source Type: `{source['source_type']}`
- URI/Path: `{source.get('uri') or source.get('path') or 'manual'}`
- SHA256: `{source['sha256']}`
- Trust Score: `{source['trust_score']}`

## Summary

{summary}

## Extracted Claims

{claim_lines}

## Next Processing

- Review source quality.
- Check contradictions.
- Promote claims only when evidence is sufficient.
"""
    return write_note(
        root,
        "source",
        f"Source - {source['title']} - {source['sha256'][:8]}",
        body,
        metadata={
            "source_id": source["source_id"],
            "source_type": source["source_type"],
            "sha256": source["sha256"],
            "trust_score": source["trust_score"],
            "tags": ["sniper/source", f"source/{source['source_type']}"],
        },
        folder="03_Sources",
        overwrite=True,
    )


def _claim_objects(source_id: str, claims: list[str], trust: float) -> list[dict[str, Any]]:
    result = []
    for claim in claims:
        result.append({
            "claim_id": new_id("claim"),
            "source_id": source_id,
            "claim": claim,
            "confidence": round(max(0.10, min(0.75, trust - 0.10)), 4),
            "status": "extracted",
            "created_at": utc_now(),
        })
    return result


def _emit_and_ledger(root: Path, source: dict[str, Any], result: dict[str, Any], summary: str) -> None:
    paths = RuntimePaths(root)
    paths.ensure()
    event = EventBus(paths.event_journal).emit(
        "ingestion.completed",
        "sniper.ingestion",
        {"source_id": source["source_id"], "claim_count": len(result.get("claims", [])), "title": source["title"]},
    )
    AppendOnlyLedger(paths.ledger).append(
        "sniper.ingestion",
        "ingestion.completed",
        "source",
        source["source_id"],
        summary,
        payload={"result": result, "event_id": event.event_id},
    )


def ingest_text(root: Path, title: str, text: str, source_type: str = "manual", uri: str | None = None) -> dict[str, Any]:
    ensure_ingestion_workspace(root)
    raw = text.encode("utf-8")
    digest = _sha256_bytes(raw)
    claims = extract_claims(text)
    score = trust_score(source_type, char_count=len(text), claim_count=len(claims))
    source = {
        "source_id": new_id("source"),
        "title": title,
        "source_type": source_type,
        "uri": uri,
        "path": None,
        "sha256": digest,
        "captured_at": utc_now(),
        "char_count": len(text),
        "trust_score": score,
    }
    raw_path = archive_dir(root) / f"{digest[:16]}.txt"
    raw_path.write_text(text, encoding="utf-8")
    source["archive_path"] = raw_path.relative_to(root).as_posix()

    summary = summarize_text(text)
    source_note = _write_source_note(root, source, summary, claims)
    digest_note = write_source_digest(root, f"{title} - {digest[:8]}", summary, claims, source_uri=uri or source.get("archive_path"))
    claim_objects = _claim_objects(source["source_id"], claims, score)
    result = {
        "ok": True,
        "ingestion_id": new_id("ingestion"),
        "created_at": utc_now(),
        "source": source,
        "summary": summary,
        "claims": claim_objects,
        "obsidian": {"source_note": source_note.get("path"), "digest_note": digest_note.get("path")},
    }
    _record_runtime(root, result)
    _emit_and_ledger(root, source, result, f"Ingested source: {title}")
    build_vault_index(root, write=True)
    return result


def ingest_file(root: Path, path: Path, title: str | None = None, source_type: str | None = None, uri: str | None = None) -> dict[str, Any]:
    ensure_ingestion_workspace(root)
    path = path.resolve()
    extracted = extract_text_from_file(path)
    text = extracted["text"]
    file_bytes = path.read_bytes()
    digest = _sha256_bytes(file_bytes)
    claims = extract_claims(text)
    inferred_type = source_type or extracted["source_type"]
    score = trust_score(inferred_type, char_count=len(text), claim_count=len(claims))
    source_title = title or _safe_title(path)
    archive_name = f"{digest[:16]}_{path.name}"
    archive_path = archive_dir(root) / archive_name
    shutil.copyfile(path, archive_path)
    source = {
        "source_id": new_id("source"),
        "title": source_title,
        "source_type": inferred_type,
        "uri": uri,
        "path": path.as_posix(),
        "archive_path": archive_path.relative_to(root).as_posix(),
        "sha256": digest,
        "captured_at": utc_now(),
        "char_count": len(text),
        "line_count": extracted.get("line_count"),
        "trust_score": score,
    }
    summary = summarize_text(text)
    source_note = _write_source_note(root, source, summary, claims)
    digest_note = write_source_digest(root, f"{source_title} - {digest[:8]}", summary, claims, source_uri=uri or archive_path.relative_to(root).as_posix())
    claim_objects = _claim_objects(source["source_id"], claims, score)
    result = {
        "ok": True,
        "ingestion_id": new_id("ingestion"),
        "created_at": utc_now(),
        "source": source,
        "summary": summary,
        "claims": claim_objects,
        "obsidian": {"source_note": source_note.get("path"), "digest_note": digest_note.get("path")},
    }
    _record_runtime(root, result)
    _emit_and_ledger(root, source, result, f"Ingested file: {source_title}")
    build_vault_index(root, write=True)
    return result


def register_url(root: Path, title: str, uri: str) -> dict[str, Any]:
    ensure_ingestion_workspace(root)
    candidate = {
        "candidate_id": new_id("external_fetch"),
        "title": title,
        "uri": uri,
        "source_type": "url_placeholder",
        "status": "queued_external_fetch",
        "created_at": utc_now(),
        "note": "Phase 03 records remote sources but does not fetch network content.",
    }
    job_path = root / "runtime_state" / "ingestion" / "jobs" / f"{candidate['candidate_id']}.json"
    write_json(job_path, candidate)
    paths = RuntimePaths(root)
    paths.ensure()
    event = EventBus(paths.event_journal).emit("external_fetch.queued", "sniper.ingestion", candidate)
    AppendOnlyLedger(paths.ledger).append(
        "sniper.ingestion",
        "external_fetch.queued",
        "external_fetch_candidate",
        candidate["candidate_id"],
        f"Queued external source: {title}",
        payload={"candidate": candidate, "event_id": event.event_id},
    )
    return {"ok": True, "candidate": candidate, "job_path": job_path.relative_to(root).as_posix()}


def process_inbox(root: Path, limit: int | None = None, archive: bool = True) -> dict[str, Any]:
    ensure_ingestion_workspace(root)
    inbox = inbox_dir(root)
    supported = {".txt", ".md", ".markdown", ".json", ".csv", ".html", ".htm"}
    files = [p for p in sorted(inbox.iterdir()) if p.is_file() and p.suffix.lower() in supported and p.name != "README.md"]
    if limit is not None:
        files = files[:limit]

    results = []
    failures = []
    for path in files:
        try:
            result = ingest_file(root, path)
            results.append(result)
            if archive:
                dest = processed_dir(root) / path.name
                if dest.exists():
                    dest = processed_dir(root) / f"{path.stem}_{result['source']['sha256'][:8]}{path.suffix}"
                shutil.move(str(path), str(dest))
        except Exception as exc:  # keep inbox processing resilient and auditable
            failures.append({"path": path.relative_to(root).as_posix(), "error": str(exc)})
            dest = rejected_dir(root) / path.name
            if dest.exists():
                dest = rejected_dir(root) / f"{path.stem}_{new_id('reject').split('.')[-1]}{path.suffix}"
            shutil.move(str(path), str(dest))

    report = {"ok": not failures, "processed_count": len(results), "failed_count": len(failures), "failures": failures, "results": results}
    write_json(root / "runtime_state" / "reports" / "ingestion_process_inbox_latest.json", report)
    return report
