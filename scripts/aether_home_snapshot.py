#!/usr/bin/env python3
"""Consistent, hash-manifested AETHER_HOME export/import tooling."""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
from typing import Any

SCHEMA = "aether.state-snapshot.v1"
SQLITE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
SIDE_CAR_SUFFIXES = {"-wal", "-shm", "-journal"}
MANIFEST_NAME = "AETHER_HOME_MANIFEST.json"
WINDOWS_PUBLISH_RETRY_ATTEMPTS = 6
WINDOWS_PUBLISH_INITIAL_DELAY_SECONDS = 0.1
WINDOWS_PUBLISH_MAX_DELAY_SECONDS = 1.0
WINDOWS_TRANSIENT_WINERRORS = {5, 32, 33}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_sqlite(path: Path) -> bool:
    return path.suffix.lower() in SQLITE_SUFFIXES


def is_sidecar(path: Path) -> bool:
    name = path.name.lower()
    return any(name.endswith(suffix) for suffix in SIDE_CAR_SUFFIXES)


def sqlite_check(path: Path) -> str:
    try:
        connection = sqlite3.connect(
            f"file:{path.as_posix()}?mode=ro",
            uri=True,
            timeout=30,
        )
        with closing(connection) as conn:
            row = conn.execute("PRAGMA quick_check").fetchone()
            return str(row[0]) if row else "no-result"
    except sqlite3.DatabaseError as exc:
        return f"error:{type(exc).__name__}:{exc}"


def backup_sqlite(source: Path, destination: Path) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_check = sqlite_check(source)
    if source_check != "ok":
        raise RuntimeError(f"source SQLite quick_check failed for {source}: {source_check}")
    source_connection = sqlite3.connect(
        f"file:{source.as_posix()}?mode=ro",
        uri=True,
        timeout=30,
    )
    with closing(source_connection) as src:
        with closing(sqlite3.connect(destination, timeout=30)) as dst:
            src.backup(dst)
            dst.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    destination_check = sqlite_check(destination)
    if destination_check != "ok":
        raise RuntimeError(
            f"snapshot SQLite quick_check failed for {destination}: "
            f"{destination_check}"
        )
    return {
        "source_quick_check": source_check,
        "snapshot_quick_check": destination_check,
    }


def _manifest_entries(root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name == MANIFEST_NAME or is_sidecar(path):
            continue
        relative = path.relative_to(root).as_posix()
        entries.append({
            "path": relative,
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "kind": "sqlite" if is_sqlite(path) else "file",
        })
    return entries


def verify_snapshot(root: Path) -> dict[str, Any]:
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file():
        raise FileNotFoundError(f"snapshot manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != SCHEMA:
        raise ValueError(f"unsupported snapshot schema: {manifest.get('schema')}")
    errors: list[str] = []
    for entry in manifest.get("files", []):
        path = root / str(entry["path"])
        if not path.is_file():
            errors.append(f"missing:{entry['path']}")
            continue
        if path.stat().st_size != int(entry["size_bytes"]):
            errors.append(f"size:{entry['path']}")
        if sha256_file(path) != str(entry["sha256"]):
            errors.append(f"sha256:{entry['path']}")
        if entry.get("kind") == "sqlite":
            check = sqlite_check(path)
            if check != "ok":
                errors.append(f"sqlite:{entry['path']}:{check}")
    actual = {item["path"] for item in _manifest_entries(root)}
    expected = {str(item["path"]) for item in manifest.get("files", [])}
    for extra in sorted(actual - expected):
        errors.append(f"extra:{extra}")
    return {
        "schema": SCHEMA,
        "status": "ok" if not errors else "failed",
        "root": str(root),
        "file_count": len(expected),
        "errors": errors,
    }


def _is_windows() -> bool:
    return os.name == "nt"


def _is_transient_windows_error(error: OSError) -> bool:
    return _is_windows() and (
        isinstance(error, PermissionError)
        or getattr(error, "winerror", None) in WINDOWS_TRANSIENT_WINERRORS
    )


def _retry_delay(attempt: int) -> float:
    return min(
        WINDOWS_PUBLISH_INITIAL_DELAY_SECONDS * (2**attempt),
        WINDOWS_PUBLISH_MAX_DELAY_SECONDS,
    )


def _remove_tree_with_retry(path: Path) -> None:
    for attempt in range(WINDOWS_PUBLISH_RETRY_ATTEMPTS):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except OSError as error:
            if (
                not _is_transient_windows_error(error)
                or attempt == WINDOWS_PUBLISH_RETRY_ATTEMPTS - 1
            ):
                raise
            time.sleep(_retry_delay(attempt))


def _best_effort_remove_tree(path: Path) -> None:
    try:
        _remove_tree_with_retry(path)
    except OSError:
        pass


def _publish_snapshot(temp: Path, output: Path) -> dict[str, Any]:
    last_error: OSError | None = None
    for attempt in range(WINDOWS_PUBLISH_RETRY_ATTEMPTS):
        try:
            os.replace(temp, output)
            return {"method": "replace", "attempts": attempt + 1}
        except OSError as error:
            if not _is_transient_windows_error(error):
                raise
            last_error = error
            if attempt < WINDOWS_PUBLISH_RETRY_ATTEMPTS - 1:
                time.sleep(_retry_delay(attempt))

    if last_error is None:
        raise RuntimeError("snapshot publish retry exhausted without an error")

    try:
        shutil.copytree(temp, output, copy_function=shutil.copy2)
        verification = verify_snapshot(output)
        if verification["status"] != "ok":
            raise RuntimeError(
                f"fallback snapshot verification failed: {verification['errors']}"
            )
    except Exception:
        _best_effort_remove_tree(output)
        raise

    _remove_tree_with_retry(temp)
    return {
        "method": "verified-copy",
        "attempts": WINDOWS_PUBLISH_RETRY_ATTEMPTS,
        "replace_error": f"{type(last_error).__name__}:{last_error}",
    }


def export_snapshot(source: Path, output: Path) -> dict[str, Any]:
    source = source.resolve()
    output = output.resolve()
    if not source.is_dir():
        raise NotADirectoryError(source)
    if source == output or source in output.parents:
        raise ValueError("snapshot output must not be inside AETHER_HOME")
    if output.exists():
        raise FileExistsError(f"snapshot destination already exists: {output}")

    output.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    database_receipts: dict[str, Any] = {}
    try:
        for path in sorted(item for item in source.rglob("*") if item.is_file()):
            relative = path.relative_to(source)
            if is_sidecar(path):
                continue
            destination = temp / relative
            if is_sqlite(path):
                database_receipts[relative.as_posix()] = backup_sqlite(path, destination)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
        entries = _manifest_entries(temp)
        manifest = {
            "schema": SCHEMA,
            "source_root": str(source),
            "files": entries,
            "database_receipts": database_receipts,
            "sidecars_excluded": ["*-wal", "*-shm", "*-journal"],
        }
        (temp / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        verification = verify_snapshot(temp)
        if verification["status"] != "ok":
            raise RuntimeError(f"snapshot verification failed: {verification['errors']}")
        publish = _publish_snapshot(temp, output)
    except Exception:
        _best_effort_remove_tree(temp)
        raise
    return {
        "schema": SCHEMA,
        "status": "exported",
        "source": str(source),
        "snapshot": str(output),
        "files": len(entries),
        "databases": len(database_receipts),
        "publish_method": publish["method"],
        "publish_attempts": publish["attempts"],
    }


def import_snapshot(
    snapshot: Path,
    destination: Path,
    *,
    allow_nonempty: bool = False,
) -> dict[str, Any]:
    snapshot = snapshot.resolve()
    destination = destination.resolve()
    verification = verify_snapshot(snapshot)
    if verification["status"] != "ok":
        raise RuntimeError(f"source snapshot is invalid: {verification['errors']}")
    destination.mkdir(parents=True, exist_ok=True)
    existing = [item for item in destination.iterdir() if item.name != "provisioning-evidence"]
    if existing and not allow_nonempty:
        raise RuntimeError("destination AETHER_HOME is not empty")
    manifest = json.loads((snapshot / MANIFEST_NAME).read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        source = snapshot / entry["path"]
        target = destination / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not allow_nonempty:
            raise FileExistsError(target)
        shutil.copy2(source, target)
    imported_entries = _manifest_entries(destination)
    imported_by_path = {entry["path"]: entry for entry in imported_entries}
    errors = []
    for entry in manifest["files"]:
        actual = imported_by_path.get(entry["path"])
        if actual is None or actual["sha256"] != entry["sha256"]:
            errors.append(entry["path"])
    if errors:
        raise RuntimeError(f"import hash verification failed: {errors[:10]}")
    return {
        "schema": SCHEMA,
        "status": "imported",
        "snapshot": str(snapshot),
        "destination": str(destination),
        "files": len(manifest["files"]),
        "databases": sum(1 for item in manifest["files"] if item["kind"] == "sqlite"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export")
    export.add_argument("--source", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--snapshot", type=Path, required=True)
    restore = sub.add_parser("import")
    restore.add_argument("--snapshot", type=Path, required=True)
    restore.add_argument("--destination", type=Path, required=True)
    restore.add_argument("--allow-nonempty", action="store_true")
    args = parser.parse_args()
    if args.command == "export":
        result = export_snapshot(args.source, args.output)
    elif args.command == "verify":
        result = verify_snapshot(args.snapshot)
    else:
        result = import_snapshot(
            args.snapshot,
            args.destination,
            allow_nonempty=args.allow_nonempty,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("status") != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
