"""Durable workspace bindings and append-only coding-runtime telemetry."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from aether.contracts.coding_runtime import WorkspaceBinding
from aether.utils.ids import new_id
from aether.utils.time import utc_now_iso


class WorkspaceBindingError(RuntimeError):
    pass


class SQLiteWorkspaceBindingStore:
    def __init__(self, path: Path, allowed_roots: Sequence[Path]) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.allowed_roots = tuple(item.expanduser().resolve() for item in allowed_roots)
        if not self.allowed_roots:
            raise WorkspaceBindingError("at least one allowed workspace root is required")
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS workspace_bindings (
                    binding_id TEXT PRIMARY KEY,
                    workspace_id TEXT UNIQUE NOT NULL,
                    root_path TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    allowed_relative_paths TEXT NOT NULL,
                    writable INTEGER NOT NULL,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS workspace_bindings_no_update
                BEFORE UPDATE ON workspace_bindings BEGIN SELECT RAISE(ABORT, 'workspace bindings are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS workspace_bindings_no_delete
                BEFORE DELETE ON workspace_bindings BEGIN SELECT RAISE(ABORT, 'workspace bindings are immutable'); END;
            """)

    def bind(self, root: Path, session_id: str, *, workspace_id: str | None = None,
             allowed_relative_paths: Sequence[str] = (".",), writable: bool = True,
             metadata: Mapping[str, Any] | None = None) -> WorkspaceBinding:
        resolved = root.expanduser().resolve()
        if not resolved.exists() or not resolved.is_dir():
            raise WorkspaceBindingError(f"workspace root does not exist or is not a directory: {resolved}")
        if not any(_is_relative_to(resolved, allowed) for allowed in self.allowed_roots):
            raise WorkspaceBindingError("workspace root is outside configured allowed roots")
        session = session_id.strip()
        if not session:
            raise WorkspaceBindingError("session_id is required")
        wid = workspace_id or new_id("workspace")
        binding = WorkspaceBinding(
            workspace_id=wid, root_path=str(resolved), session_id=session,
            allowed_relative_paths=tuple(str(item) for item in allowed_relative_paths),
            writable=bool(writable), metadata=dict(metadata or {}),
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO workspace_bindings VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (binding.binding_id, binding.workspace_id, binding.root_path, binding.session_id,
                 json.dumps(binding.allowed_relative_paths), int(binding.writable),
                 json.dumps(dict(binding.metadata), sort_keys=True), utc_now_iso()),
            )
        return binding

    def resolve(self, workspace_id: str, session_id: str) -> WorkspaceBinding:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM workspace_bindings WHERE workspace_id = ?", (workspace_id,)).fetchone()
        if row is None:
            raise WorkspaceBindingError(f"workspace binding not found: {workspace_id}")
        if row["session_id"] != session_id:
            raise WorkspaceBindingError("workspace binding is owned by a different session")
        root = Path(row["root_path"]).resolve()
        if not root.exists() or not root.is_dir():
            raise WorkspaceBindingError("bound workspace is no longer available")
        if not any(_is_relative_to(root, allowed) for allowed in self.allowed_roots):
            raise WorkspaceBindingError("bound workspace no longer satisfies allowed roots")
        return WorkspaceBinding(
            workspace_id=row["workspace_id"], root_path=row["root_path"], session_id=row["session_id"],
            allowed_relative_paths=tuple(json.loads(row["allowed_relative_paths"])),
            writable=bool(row["writable"]), metadata=json.loads(row["metadata"]),
            binding_id=row["binding_id"],
        )

    def list_bindings(self, *, session_id: str | None = None, limit: int = 200) -> tuple[WorkspaceBinding, ...]:
        query = "SELECT * FROM workspace_bindings"
        params: tuple[Any, ...] = ()
        if session_id:
            query += " WHERE session_id = ?"
            params = (session_id,)
        query += " ORDER BY created_at DESC LIMIT ?"
        params = (*params, max(1, min(limit, 1000)))
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return tuple(WorkspaceBinding(
            workspace_id=row["workspace_id"], root_path=row["root_path"], session_id=row["session_id"],
            allowed_relative_paths=tuple(json.loads(row["allowed_relative_paths"])), writable=bool(row["writable"]),
            metadata=json.loads(row["metadata"]), binding_id=row["binding_id"],
        ) for row in rows)


class RuntimeTelemetryStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS runtime_progress (
                    progress_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, sequence INTEGER NOT NULL,
                    phase TEXT NOT NULL, message TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runtime_invocations (
                    invocation_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, adapter_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL, session_id TEXT NOT NULL, ok INTEGER NOT NULL,
                    status TEXT NOT NULL, duration_seconds REAL NOT NULL, artifact_count INTEGER NOT NULL,
                    verification_count INTEGER NOT NULL, failure_fingerprint TEXT, payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS runtime_progress_no_update BEFORE UPDATE ON runtime_progress
                BEGIN SELECT RAISE(ABORT, 'runtime progress is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS runtime_progress_no_delete BEFORE DELETE ON runtime_progress
                BEGIN SELECT RAISE(ABORT, 'runtime progress is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS runtime_invocations_no_update BEFORE UPDATE ON runtime_invocations
                BEGIN SELECT RAISE(ABORT, 'runtime telemetry is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS runtime_invocations_no_delete BEFORE DELETE ON runtime_invocations
                BEGIN SELECT RAISE(ABORT, 'runtime telemetry is append-only'); END;
            """)

    def record_progress(self, progress) -> None:
        with self._connect() as conn:
            conn.execute("INSERT INTO runtime_progress VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (progress.progress_id, progress.task_id, progress.sequence, progress.phase,
                          progress.message, json.dumps(asdict(progress), sort_keys=True, default=str), utc_now_iso()))

    def record_invocation(self, *, task_id: str, adapter_id: str, workspace_id: str, session_id: str,
                          ok: bool, status: str, duration_seconds: float, artifact_count: int,
                          verification_count: int, failure_fingerprint: str | None,
                          payload: Mapping[str, Any]) -> str:
        invocation_id = new_id("runtime-invocation")
        with self._connect() as conn:
            conn.execute("INSERT INTO runtime_invocations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (invocation_id, task_id, adapter_id, workspace_id, session_id, int(ok), status,
                          duration_seconds, artifact_count, verification_count, failure_fingerprint,
                          json.dumps(dict(payload), sort_keys=True, default=str), utc_now_iso()))
        return invocation_id

    def status(self) -> Mapping[str, int]:
        with self._connect() as conn:
            invocations = conn.execute("SELECT COUNT(*) FROM runtime_invocations").fetchone()[0]
            progress = conn.execute("SELECT COUNT(*) FROM runtime_progress").fetchone()[0]
        return {"invocations": int(invocations), "progress_events": int(progress)}

    def list_invocations(self, *, adapter_id: str | None = None, limit: int = 100) -> tuple[Mapping[str, Any], ...]:
        query = "SELECT * FROM runtime_invocations"
        params: list[Any] = []
        if adapter_id:
            query += " WHERE adapter_id = ?"
            params.append(adapter_id)
        query += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
        params.append(max(1, min(limit, 1000)))
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return tuple({
            "invocation_id": row["invocation_id"],
            "task_id": row["task_id"],
            "adapter_id": row["adapter_id"],
            "workspace_id": row["workspace_id"],
            "session_id": row["session_id"],
            "ok": bool(row["ok"]),
            "status": row["status"],
            "duration_seconds": float(row["duration_seconds"]),
            "artifact_count": int(row["artifact_count"]),
            "verification_count": int(row["verification_count"]),
            "failure_fingerprint": row["failure_fingerprint"],
            "payload": json.loads(row["payload"]),
            "created_at": row["created_at"],
        } for row in rows)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
