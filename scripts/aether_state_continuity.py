#!/usr/bin/env python3
"""Inspect Aether mutable state, create a live tool proof, and preserve legacy brain data.

This utility is intentionally conservative:
- it never prints secrets;
- it never mutates canonical SQLite stores;
- legacy state is preserved as evidence/candidates, not silently promoted;
- migration is dry-run unless --apply is passed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import secrets
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def default_home() -> Path:
    if platform.system() == "Windows":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "Aether"
        return Path.home() / "AppData" / "Local" / "Aether"
    return Path.home() / ".aether"


def resolve_home(release_root: Path | None, explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("AETHER_HOME")
    if env:
        return Path(env).expanduser().resolve()
    if release_root:
        values = read_env_file(release_root / "aether-core" / ".env")
        configured = values.get("AETHER_HOME")
        if configured:
            return Path(configured).expanduser().resolve()
    return default_home().resolve()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


_SENSITIVE_NAME_MARKERS = (
    "api_key", "api-keys", "api keys", "credential", "credentials",
    "secret", "secrets", "password", "passwd", "private_key",
    "private-key", "access_token", "refresh_token", "auth_token",
)


def looks_sensitive(path: Path) -> bool:
    normalized = path.name.casefold().replace("-", "_")
    return any(marker.replace("-", "_") in normalized for marker in _SENSITIVE_NAME_MARKERS)


def sqlite_summary(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "size_bytes": path.stat().st_size if path.is_file() else 0,
        "tables": {},
        "group_counts": {},
        "error": None,
    }
    if not path.is_file():
        return result
    try:
        uri = f"file:{path.as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=2.0) as conn:
            names = [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                ).fetchall()
            ]
            for name in names:
                escaped = name.replace('"', '""')
                try:
                    count = conn.execute(f'SELECT COUNT(*) FROM "{escaped}"').fetchone()[0]
                except sqlite3.Error:
                    count = None
                result["tables"][name] = count

            grouped_queries = {
                "memory_by_namespace": (
                    "memory_records",
                    "SELECT namespace, COUNT(*) FROM memory_records GROUP BY namespace ORDER BY namespace",
                ),
                "memory_by_kind": (
                    "memory_records",
                    "SELECT kind, COUNT(*) FROM memory_records GROUP BY kind ORDER BY kind",
                ),
                "pending_actions_by_status": (
                    "pending_actions",
                    "SELECT status, COUNT(*) FROM pending_actions GROUP BY status ORDER BY status",
                ),
                "approval_records_by_decision": (
                    "approval_records",
                    "SELECT decision, COUNT(*) FROM approval_records GROUP BY decision ORDER BY decision",
                ),
            }
            available = set(names)
            for label, (required_table, query) in grouped_queries.items():
                if required_table not in available:
                    continue
                try:
                    result["group_counts"][label] = {
                        str(key): int(value) for key, value in conn.execute(query).fetchall()
                    }
                except sqlite3.Error:
                    result["group_counts"][label] = None
    except Exception as exc:  # audit must continue
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def safe_json_summary(path: Path, allowed_keys: tuple[str, ...]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "size_bytes": path.stat().st_size if path.is_file() else 0,
        "values": {},
        "error": None,
    }
    if not path.is_file():
        return result
    try:
        raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        if isinstance(raw, dict):
            result["values"] = {key: raw.get(key) for key in allowed_keys if key in raw}
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def directory_summary(path: Path) -> dict[str, Any]:
    files = [item for item in path.rglob("*") if item.is_file()] if path.is_dir() else []
    return {
        "path": str(path),
        "exists": path.is_dir(),
        "files": len(files),
        "size_bytes": sum(item.stat().st_size for item in files),
    }


def state_map(home: Path) -> dict[str, Any]:
    paths = {
        "sessions": home / "sessions" / "cognitive-sessions.sqlite3",
        "canonical_memory": home / "memory" / "canonical-episodes.sqlite3",
        "retrieval_index": home / "memory" / "retrieval-index.sqlite3",
        "knowledge_proposals": home / "memory" / "knowledge-proposals.sqlite3",
        "skill_factory": home / "skills" / "skill-factory.sqlite3",
        "legacy_hub_runtime_tool_memory": home / "aether_hub.db",
        "core_hub": home / "db" / "aether_hub.db",
        "knowledge_graph": home / "db" / "knowledge_graph.db",
        "governance": home / "db" / "governance_ledger.db",
        "mission_orchestrator": home / "missions" / "mission-orchestrator.sqlite3",
        "pending_actions": home / "governance" / "pending-actions.sqlite3",
        "internal_evolution": home / "evolution" / "internal-evolution.sqlite3",
        "workspace_bindings": home / "runtime" / "workspace-bindings.sqlite3",
        "runtime_telemetry": home / "runtime" / "runtime-telemetry.sqlite3",
        "fleet_operations": home / "runtime" / "fleet-operations.sqlite3",
        "opportunity_intelligence": home / "opportunities" / "opportunity-intelligence.sqlite3",
        "live_web_intelligence": home / "web-intelligence" / "live-web-intelligence.sqlite3",
        "reversible_experiments": home / "experiments" / "reversible-experiments.sqlite3",
        "browser_senses": home / "senses" / "browser-senses.sqlite3",
    }
    vault = home / "obsidian" / "vault"
    registry = home / "skills" / "registry"
    database_state = {name: sqlite_summary(path) for name, path in paths.items()}
    canonical_count = database_state["canonical_memory"]["tables"].get("memory_records")
    indexed_count = database_state["retrieval_index"]["tables"].get("indexed_records")
    return {
        "schema": "aether.state-continuity.audit.v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "aether_home": str(home),
        "home_exists": home.is_dir(),
        "databases": database_state,
        "behavior_monitor": {
            "trust_score": safe_json_summary(
                home / "runtime_state" / "trust_score.json", ("score", "updated_at")
            ),
            "profile_start": safe_json_summary(
                home / "runtime_state" / "profile_start.json", ("start_time",)
            ),
            "quarantine_state": safe_json_summary(
                home / "runtime_state" / "quarantine_state.json",
                ("in_quarantine", "quarantine_start", "quarantine_reason", "original_profile"),
            ),
        },
        "directories": {
            "obsidian_vault": {
                **directory_summary(vault),
                "markdown_files": len(list(vault.rglob("*.md"))) if vault.is_dir() else 0,
            },
            "skill_registry": directory_summary(registry),
            "skill_sandboxes": directory_summary(home / "skills" / "sandboxes"),
            "skill_runtime_projections": directory_summary(home / "skills" / "runtime-projections"),
            "legacy_knowledge_workspace": directory_summary(home / "runtime_state" / "knowledge"),
            "workspace": directory_summary(home / "workspace"),
            "events": directory_summary(home / "events"),
            "browser_frames": directory_summary(home / "senses" / "frames"),
            "runtime_state_reports": directory_summary(home / "runtime_state" / "reports"),
        },
        "consistency": {
            "canonical_memory_records": canonical_count,
            "retrieval_index_records": indexed_count,
            "memory_index_aligned": (
                canonical_count is not None and indexed_count is not None and canonical_count == indexed_count
            ),
        },
        "notes": [
            "Obsidian is a rebuildable projection, not canonical memory authority.",
            "Promoted knowledge is stored in canonical-episodes.sqlite3 with namespace=knowledge; proposals and decisions are stored in knowledge-proposals.sqlite3.",
            "The root aether_hub.db is currently used by the operational MemoryTool; db/aether_hub.db belongs to the older core hub database manager.",
            "Behavior-monitor summaries expose only non-secret status fields.",
        ],
    }


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str))


def classify_legacy_path(relative_path: Path) -> tuple[str, str]:
    """Classify a legacy file without reading its content.

    The classification is intentionally path-based. A preservation run must not
    accidentally open credentials merely to decide that they are credentials.
    """

    parts = tuple(part.casefold() for part in relative_path.parts)
    name = relative_path.name.casefold()
    if name in {".env", ".env.local"} or looks_sensitive(relative_path):
        return "secret_quarantine", "hash_only"
    if ".obsidian" in parts:
        return "local_obsidian_configuration", "preserve_only"
    if name in {"hermes_hub.db", "hermes_hub.db-shm", "hermes_hub.db-wal"}:
        return "forensic_database", "preserve_immutable"
    if parts and parts[0] == "skills":
        return "legacy_skill_candidate", "candidate_review"
    if "knowledge" in parts or "claim_registry" in name or name == "registry.json":
        return "legacy_knowledge_candidate", "candidate_review"
    if parts and parts[0] == "20_dee_workspace":
        return "founder_workspace_archive", "human_review"
    if "obsidian" in parts and "vault" in parts:
        return "legacy_vault_archive", "aether_review_later"
    if any(marker in name for marker in ("goal", "decision", "strategy", "reflection", "diary")):
        return "legacy_context_candidate", "candidate_review"
    return "legacy_archive", "preserve_only"


def inventory_legacy_tree(source: Path, archive_root: Path, *, apply: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Hash every file and optionally preserve non-secret bytes in an inert archive.

    No file is copied into active memory, skills, knowledge, workspace, or
    Obsidian paths. Potential-secret material is hash-only and remains at the
    Founder-controlled source location.
    """

    files: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    for item in sorted(source.rglob("*")):
        if not item.is_file():
            continue
        rel = item.relative_to(source)
        if any(part.casefold() in {".git", "__pycache__"} for part in rel.parts):
            continue
        classification, import_action = classify_legacy_path(rel)
        record = {
            "source": str(item),
            "relative_path": rel.as_posix(),
            "size_bytes": item.stat().st_size,
            "sha256": sha256_file(item),
            "classification": classification,
            "import_action": import_action,
            "copied": False,
        }
        if classification == "secret_quarantine":
            record["reason"] = (
                "Potential-secret material is excluded from Aether storage, "
                "semantic indexing, model context, and Obsidian projection."
            )
            quarantined.append(record)
            continue

        destination = archive_root / "payload" / rel
        record["target"] = str(destination)
        if apply:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)
            record["copied"] = True
        files.append(record)
    return files, quarantined


def migrate_legacy(source: Path, home: Path, apply: bool) -> dict[str, Any]:
    source = source.expanduser().resolve()
    if not source.is_dir():
        raise SystemExit(f"Legacy brain root does not exist: {source}")
    import_id = f"legacy-brain-{utc_stamp()}"
    archive_root = home / "legacy" / "archives" / "original-brain" / import_id
    files, quarantined = inventory_legacy_tree(source, archive_root, apply=apply)
    classification_counts: dict[str, int] = {}
    action_counts: dict[str, int] = {}
    for item in (*files, *quarantined):
        classification = str(item["classification"])
        action = str(item["import_action"])
        classification_counts[classification] = classification_counts.get(classification, 0) + 1
        action_counts[action] = action_counts.get(action, 0) + 1

    result = {
        "schema": "aether.legacy-state-preservation.v2",
        "mode": "apply" if apply else "dry-run",
        "source": str(source),
        "aether_home": str(home),
        "import_id": import_id,
        "archive_root": str(archive_root),
        "file_count": len(files),
        "files": files,
        "quarantined_file_count": len(quarantined),
        "quarantined_files": quarantined,
        "classification_counts": dict(sorted(classification_counts.items())),
        "action_counts": dict(sorted(action_counts.items())),
        "semantic_migration": {
            "performed": False,
            "reason": (
                "The original brain is ancestry and project history, not current "
                "autobiographical memory. No legacy file is inserted into canonical "
                "memory, retrieval, Skill Factory, governed knowledge, workspace, or "
                "the live Obsidian projection."
            ),
        },
        "security": {
            "env_files_copied": False,
            "obsidian_settings_copied": False,
            "potential_secret_documents_copied": False,
            "quarantine_policy": "hash-and-report only; source bytes remain under Founder control",
            "archive_is_inert": True,
            "archive_indexing_authorized": False,
        },
        "promotion_boundary": {
            "automatic_imports_authorized": 0,
            "candidate_review_required": True,
            "founder_or_governance_approval_required": True,
        },
    }
    if apply:
        manifest_path = archive_root / "manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["manifest_path"] = str(manifest_path)
    return result


def create_tool_proof(home: Path) -> dict[str, Any]:
    nonce = secrets.token_hex(12)
    path = home / "workspace" / "tool-proof.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        "AETHER_LIVE_TOOL_PROOF\n"
        f"NONCE={nonce}\n"
        "This content was created locally and must be returned only through the governed read tool.\n"
    )
    path.write_text(content, encoding="utf-8")
    state = home / "runtime_state" / "tool-proof.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"nonce": nonce, "path": str(path), "created_at": datetime.now(timezone.utc).isoformat()}, indent=2), encoding="utf-8")
    prompt = (
        "Aether, lakukan live tool conformance test. Gunakan capability read melalui native governed tool call "
        f"untuk membaca file `{path}`. Jangan menebak isi dan jangan hanya menulis tag [TOOL] sebagai teks. "
        "Setelah menerima action result, balas dengan full path dan nilai NONCE persis seperti di file."
    )
    return {"path": str(path), "nonce": nonce, "state_path": str(state), "telegram_prompt": prompt}


def verify_tool_proof(home: Path) -> dict[str, Any]:
    state = home / "runtime_state" / "tool-proof.json"
    if not state.is_file():
        return {"verified": False, "reason": "tool proof state is missing; run create-tool-proof first"}
    data = json.loads(state.read_text(encoding="utf-8"))
    nonce = str(data.get("nonce") or "")
    event_path = home / "events" / "action-path.jsonl"
    matches: list[dict[str, Any]] = []
    if event_path.is_file():
        for line_number, raw in enumerate(event_path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if nonce and nonce in raw:
                try:
                    item = json.loads(raw)
                except json.JSONDecodeError:
                    item = {"raw": raw}
                matches.append({"line": line_number, "event": item})
    return {
        "verified": bool(matches),
        "nonce": nonce,
        "expected_path": data.get("path"),
        "action_event_log": str(event_path),
        "matching_receipts": matches[-5:],
        "interpretation": "Founder-proven model→governance→read-tool→result loop" if matches else "No authoritative action receipt containing the nonce was found yet.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-root", type=Path, help="Aether release root used to inspect aether-core/.env")
    parser.add_argument("--aether-home", help="Explicit AETHER_HOME override")
    sub = parser.add_subparsers(dest="command", required=True)

    inspect_p = sub.add_parser("inspect", help="Print paths, existence, and SQLite table counts")
    inspect_p.add_argument("--output", type=Path)

    migrate_p = sub.add_parser("migrate-legacy", help="Preserve legacy hermes-brain state without silent promotion")
    migrate_p.add_argument("--source", type=Path, required=True)
    migrate_p.add_argument("--apply", action="store_true")
    migrate_p.add_argument("--output", type=Path)

    sub.add_parser("create-tool-proof", help="Create a sentinel file and a Telegram verification prompt")
    sub.add_parser("verify-tool-proof", help="Find an authoritative read-tool receipt containing the sentinel nonce")

    args = parser.parse_args()
    release_root = args.release_root.expanduser().resolve() if args.release_root else None
    home = resolve_home(release_root, args.aether_home)

    if args.command == "inspect":
        result = state_map(home)
    elif args.command == "migrate-legacy":
        result = migrate_legacy(args.source, home, args.apply)
    elif args.command == "create-tool-proof":
        result = create_tool_proof(home)
    elif args.command == "verify-tool-proof":
        result = verify_tool_proof(home)
    else:
        raise AssertionError(args.command)

    output = getattr(args, "output", None)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str), encoding="utf-8")
    print_json(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
