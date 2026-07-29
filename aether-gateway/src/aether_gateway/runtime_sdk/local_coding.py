"""First reference coding body: bounded structured edits with verification.

This adapter is intentionally deterministic. The intelligence that proposes
edits may come from any model or coding runtime; this body owns only the safe,
auditable filesystem and verification boundary.
"""
from __future__ import annotations

import asyncio
import difflib
import hashlib
import json
import os
import shutil
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from aether.contracts import RuntimeCommand, RuntimeResult
from aether.contracts.coding_runtime import (
    CodingArtifact, CodingArtifactKind, CodingExecutionStatus, CodingTaskResult,
    RuntimeDescriptor, RuntimeHealthStatus, RuntimeProgress, VerificationReceipt,
    coding_task_fingerprint,
)
from aether.contracts.event_types import EventType
from aether.events import EventBus
from aether.utils.ids import new_id

from .sdk import CodingRuntimeAdapterBase
from .store import RuntimeTelemetryStore


class CodingRuntimeError(RuntimeError):
    pass


class LocalStructuredCodingRuntimeAdapter(CodingRuntimeAdapterBase):
    OPERATION = "coding.task.execute"

    def __init__(
        self,
        state_root: Path,
        telemetry: RuntimeTelemetryStore,
        *,
        allowed_workspace_roots: tuple[Path, ...] | list[Path] | None = None,
        event_bus: EventBus | None = None,
        routing_key: str = "runtime://coding/local-structured",
        max_files: int = 10,
        max_total_bytes: int = 262144,
        max_diff_chars: int = 16000,
    ) -> None:
        self.state_root = state_root.resolve()
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.telemetry = telemetry
        self.allowed_workspace_roots = tuple(item.expanduser().resolve() for item in (allowed_workspace_roots or ()))
        if not self.allowed_workspace_roots:
            raise CodingRuntimeError("at least one allowed workspace root is required")
        self.event_bus = event_bus
        self.routing_key = routing_key
        self.max_files = max(1, max_files)
        self.max_total_bytes = max(1, max_total_bytes)
        self.max_diff_chars = max(1000, max_diff_chars)

    @property
    def adapter_id(self) -> str:
        return "runtime.coding.local-structured"

    @property
    def descriptor(self) -> RuntimeDescriptor:
        return RuntimeDescriptor(
            routing_key=self.routing_key,
            adapter_id=self.adapter_id,
            display_name="Aether Local Structured Coding Runtime",
            operations=(self.OPERATION,),
            capabilities=("coding.edit", "coding.verify", "coding.artifact-return"),
            runtime_features=(
                "structured-edits", "json-io", "workspace-binding", "progress-events",
                "bounded-artifacts", "verification-receipts", "rollback-on-failure", "no-shell",
            ),
            health_status=RuntimeHealthStatus.HEALTHY,
            priority=20,
            metadata={
                "authority": "body_only",
                "network": False,
                "shell": False,
                "arbitrary_code_generation": False,
            },
        )

    async def capabilities(self) -> set[str]:
        return {self.OPERATION}

    async def health(self) -> Mapping[str, Any]:
        probe = self.state_root / ".health-probe"
        try:
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return {
                "ok": True,
                "adapter_id": self.adapter_id,
                "routing_key": self.routing_key,
                "state_root": str(self.state_root),
                "features": list(self.descriptor.runtime_features),
                "allowed_workspace_roots": [str(item) for item in self.allowed_workspace_roots],
            }
        except Exception as exc:
            return {"ok": False, "adapter_id": self.adapter_id, "error": f"{type(exc).__name__}: {exc}"}

    async def execute(self, command: RuntimeCommand) -> RuntimeResult:
        if command.command != self.OPERATION:
            return RuntimeResult(False, error=f"Unsupported coding command: {command.command}", metadata={"error_type": "CommandDenied"})
        started = time.monotonic()
        payload = dict(command.arguments)
        task_data = dict(payload.get("task") or {})
        binding = dict(payload.get("workspace_binding") or {})
        task_id = str(task_data.get("task_id") or new_id("coding-task"))
        workspace_id = str(task_data.get("workspace_id") or "")
        session_id = str(task_data.get("session_id") or "")
        progress: list[RuntimeProgress] = []
        artifacts: list[CodingArtifact] = []
        receipts: list[VerificationReceipt] = []
        rollback_performed = False
        try:
            root = self._validate_binding(binding, workspace_id, session_id)
            edits = tuple(dict(item) for item in task_data.get("edits") or ())
            commands = tuple(dict(item) for item in task_data.get("verification_commands") or ())
            self._validate_limits(edits, task_data)
            self._progress(progress, task_id, "accepted", "Coding task accepted by bounded runtime.", 1, 5.0, command.correlation_id)
            backup_root = self.state_root / "backups" / task_id
            if backup_root.exists():
                raise CodingRuntimeError("task ID already has a backup lineage; replay is denied")
            backup_root.mkdir(parents=True, exist_ok=False)
            change_state = self._prepare_changes(root, binding, edits, backup_root)
            self._progress(progress, task_id, "prepared", "Workspace edits validated and backups created.", 2, 25.0, command.correlation_id)
            try:
                artifacts = self._apply_changes(root, change_state)
                for artifact in artifacts:
                    self._emit(EventType.CODING_ARTIFACT_RETURNED, {
                        "task_id": task_id, "artifact_id": artifact.artifact_id,
                        "path": artifact.path, "kind": artifact.kind.value,
                        "after_sha256": artifact.after_sha256, "size_bytes": artifact.size_bytes,
                    }, correlation_id=command.correlation_id)
                self._progress(progress, task_id, "edited", f"Applied {len(artifacts)} bounded artifact change(s).", 3, 55.0, command.correlation_id)
                for index, raw in enumerate(commands, start=1):
                    receipt = await self._run_verification(root, raw)
                    receipts.append(receipt)
                    self._progress(progress, task_id, "verification", f"Verification {index}/{len(commands)}: {receipt.label} {'passed' if receipt.ok else 'failed'}.", 3 + index, 55.0 + (35.0 * index / max(1, len(commands))), command.correlation_id,
                                   metadata={"receipt_id": receipt.receipt_id, "ok": receipt.ok})
                    if not receipt.ok:
                        raise CodingRuntimeError(f"verification failed: {receipt.label}")
            except Exception:
                self._rollback(root, change_state)
                rollback_performed = True
                raise
            self._progress(progress, task_id, "completed", "Coding task verified and artifact return finalized.", 1000, 100.0, command.correlation_id)
            result = CodingTaskResult(
                task_id=task_id, runtime_adapter_id=self.adapter_id, ok=True,
                status=CodingExecutionStatus.COMPLETED, artifacts=tuple(artifacts),
                verification=tuple(receipts), progress=tuple(progress), rollback_performed=False,
                metadata={"workspace_id": workspace_id, "session_id": session_id, "result_verified": True},
            )
            duration = time.monotonic() - started
            invocation_id = self.telemetry.record_invocation(
                task_id=task_id, adapter_id=self.adapter_id, workspace_id=workspace_id,
                session_id=session_id, ok=True, status=result.status.value,
                duration_seconds=duration, artifact_count=len(artifacts),
                verification_count=len(receipts), failure_fingerprint=None,
                payload={"result": _result_payload(result)},
            )
            self._emit(EventType.CODING_TASK_VERIFIED, {
                "task_id": task_id, "invocation_id": invocation_id,
                "artifact_count": len(artifacts), "verification_count": len(receipts),
                "duration_seconds": duration,
            }, correlation_id=command.correlation_id)
            return RuntimeResult(True, output=_result_payload(result), metadata={
                "adapter_id": self.adapter_id, "runtime_routing_key": self.routing_key,
                "invocation_id": invocation_id, "result_verified": True,
                "artifact_count": len(artifacts), "verification_count": len(receipts),
                "workspace_id": workspace_id, "session_id": session_id,
                "shell": False, "network": False,
            })
        except Exception as exc:
            duration = time.monotonic() - started
            failure = coding_task_fingerprint(_minimal_task(task_data), error=f"{type(exc).__name__}: {exc}")
            self._progress(progress, task_id, "failed", f"Coding task failed: {type(exc).__name__}: {exc}", 999, None, command.correlation_id,
                           metadata={"failure_fingerprint": failure})
            invocation_id = self.telemetry.record_invocation(
                task_id=task_id, adapter_id=self.adapter_id, workspace_id=workspace_id,
                session_id=session_id, ok=False, status=CodingExecutionStatus.FAILED.value,
                duration_seconds=duration, artifact_count=len(artifacts), verification_count=len(receipts),
                failure_fingerprint=failure,
                payload={"error": f"{type(exc).__name__}: {exc}", "rollback_performed": rollback_performed,
                         "artifacts": [asdict(item) for item in artifacts],
                         "verification": [asdict(item) for item in receipts]},
            )
            self._emit(EventType.CODING_TASK_FAILED, {
                "task_id": task_id, "invocation_id": invocation_id,
                "error": f"{type(exc).__name__}: {exc}",
                "failure_fingerprint": failure, "rollback_performed": rollback_performed,
            }, severity="error", correlation_id=command.correlation_id)
            return RuntimeResult(False, error=f"{type(exc).__name__}: {exc}", metadata={
                "adapter_id": self.adapter_id, "runtime_routing_key": self.routing_key,
                "invocation_id": invocation_id, "result_verified": False,
                "rollback_performed": rollback_performed, "failure_fingerprint": failure,
                "workspace_id": workspace_id, "session_id": session_id,
            })

    def _validate_binding(self, binding: Mapping[str, Any], workspace_id: str, session_id: str) -> Path:
        if str(binding.get("workspace_id") or "") != workspace_id:
            raise CodingRuntimeError("workspace binding ID mismatch")
        if str(binding.get("session_id") or "") != session_id:
            raise CodingRuntimeError("workspace binding session mismatch")
        if not bool(binding.get("writable", False)):
            raise CodingRuntimeError("workspace binding is not writable")
        root = Path(str(binding.get("root_path") or "")).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise CodingRuntimeError("workspace root is unavailable")
        if not any(_is_relative_to(root, allowed) for allowed in self.allowed_workspace_roots):
            raise CodingRuntimeError("workspace root is outside runtime allowlist")
        return root

    def _validate_limits(self, edits: tuple[Mapping[str, Any], ...], task: Mapping[str, Any]) -> None:
        max_files = min(self.max_files, max(1, int(task.get("max_artifacts", self.max_files))))
        max_bytes = min(self.max_total_bytes, max(1, int(task.get("max_total_bytes", self.max_total_bytes))))
        if not edits:
            raise CodingRuntimeError("at least one structured edit is required")
        if len(edits) > max_files:
            raise CodingRuntimeError("edit count exceeds runtime limit")
        total = sum(len(str(item.get("content") or "").encode("utf-8")) for item in edits)
        if total > max_bytes:
            raise CodingRuntimeError("edit bytes exceed runtime limit")

    def _prepare_changes(self, root: Path, binding: Mapping[str, Any], edits: tuple[Mapping[str, Any], ...], backup_root: Path) -> list[dict[str, Any]]:
        allowed = tuple(str(item) for item in binding.get("allowed_relative_paths") or (".",))
        state: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in edits:
            relative = _safe_relative_path(str(raw.get("path") or ""))
            if relative in seen:
                raise CodingRuntimeError(f"duplicate edit path: {relative}")
            seen.add(relative)
            if not _allowed_relative(relative, allowed):
                raise CodingRuntimeError(f"edit path is outside binding allowlist: {relative}")
            target = (root / relative).resolve()
            if not _is_relative_to(target, root):
                raise CodingRuntimeError(f"path traversal denied: {relative}")
            before = target.read_bytes() if target.exists() else None
            before_hash = hashlib.sha256(before).hexdigest() if before is not None else None
            expected = raw.get("expected_sha256")
            if before is not None and not expected:
                raise CodingRuntimeError(f"existing file requires expected_sha256: {relative}")
            if expected and expected != before_hash:
                raise CodingRuntimeError(f"expected_sha256 mismatch: {relative}")
            backup = backup_root / relative
            if before is not None:
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_bytes(before)
            state.append({
                "relative": relative, "target": target, "backup": backup,
                "before": before, "before_hash": before_hash,
                "content": str(raw.get("content") or ""),
            })
        return state

    def _apply_changes(self, root: Path, state: list[dict[str, Any]]) -> list[CodingArtifact]:
        artifacts: list[CodingArtifact] = []
        for item in state:
            target: Path = item["target"]
            target.parent.mkdir(parents=True, exist_ok=True)
            encoded = item["content"].encode("utf-8")
            temporary = target.with_name(target.name + ".aether-tmp")
            temporary.write_bytes(encoded)
            os.replace(temporary, target)
            after_hash = hashlib.sha256(encoded).hexdigest()
            before_text = item["before"].decode("utf-8", errors="replace") if item["before"] is not None else ""
            after_text = item["content"]
            diff = "".join(difflib.unified_diff(
                before_text.splitlines(keepends=True), after_text.splitlines(keepends=True),
                fromfile=f"a/{item['relative']}", tofile=f"b/{item['relative']}",
            ))[: self.max_diff_chars]
            artifacts.append(CodingArtifact(
                path=item["relative"],
                kind=CodingArtifactKind.MODIFIED if item["before"] is not None else CodingArtifactKind.CREATED,
                before_sha256=item["before_hash"], after_sha256=after_hash,
                size_bytes=len(encoded), diff=diff,
                metadata={"authority": "runtime_evidence", "workspace_relative": True},
            ))
        return artifacts

    async def _run_verification(self, root: Path, raw: Mapping[str, Any]) -> VerificationReceipt:
        argv = _allowed_verification_argv(tuple(str(item) for item in raw.get("argv") or ()))
        timeout = min(300.0, max(1.0, float(raw.get("timeout_seconds", 120.0))))
        label = str(raw.get("label") or "verification")
        started = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=str(root), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=_sanitized_env(),
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return VerificationReceipt(label, argv, False, None, "", f"timed out after {timeout:.1f}s", time.monotonic() - started,
                                       metadata={"timeout": True, "shell": False})
        return VerificationReceipt(
            label=label, argv=argv, ok=proc.returncode == 0, exit_code=proc.returncode,
            stdout=stdout_b.decode("utf-8", errors="replace")[-16000:],
            stderr=stderr_b.decode("utf-8", errors="replace")[-16000:],
            duration_seconds=time.monotonic() - started,
            metadata={"shell": False, "network": False},
        )

    def _rollback(self, root: Path, state: list[dict[str, Any]]) -> None:
        for item in reversed(state):
            target: Path = item["target"]
            if item["before"] is None:
                if target.exists():
                    target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(target.name + ".aether-rollback")
                temporary.write_bytes(item["before"])
                os.replace(temporary, target)

    def _progress(self, sink: list[RuntimeProgress], task_id: str, phase: str, message: str,
                  sequence: int, percent: float | None, correlation_id: str | None,
                  metadata: Mapping[str, Any] | None = None) -> None:
        item = RuntimeProgress(task_id=task_id, phase=phase, message=message, sequence=sequence,
                               percent=percent, metadata=dict(metadata or {}))
        sink.append(item)
        self.telemetry.record_progress(item)
        self._emit(EventType.CODING_TASK_PROGRESS, asdict(item), correlation_id=correlation_id)

    def _emit(self, event_type: EventType, payload: Mapping[str, Any], *, severity: str = "info",
              correlation_id: str | None = None) -> None:
        if self.event_bus is not None:
            self.event_bus.emit(event_type, actor=self.adapter_id, payload=dict(payload), severity=severity,
                                correlation_id=correlation_id)


def _minimal_task(data: Mapping[str, Any]):
    from aether.contracts.coding_runtime import CodingEdit, CodingTask, VerificationCommand
    return CodingTask(
        objective=str(data.get("objective") or "failed coding task"),
        workspace_id=str(data.get("workspace_id") or "unknown"),
        session_id=str(data.get("session_id") or "unknown"),
        edits=tuple(CodingEdit(str(item.get("path") or ""), str(item.get("content") or ""), item.get("expected_sha256")) for item in data.get("edits") or ()),
        verification_commands=tuple(VerificationCommand(tuple(str(v) for v in item.get("argv") or ()), float(item.get("timeout_seconds", 120.0)), str(item.get("label") or "verification")) for item in data.get("verification_commands") or ()),
        task_id=str(data.get("task_id") or new_id("coding-task")),
    )


def _result_payload(result: CodingTaskResult) -> dict[str, Any]:
    return {
        "task_id": result.task_id,
        "runtime_adapter_id": result.runtime_adapter_id,
        "ok": result.ok,
        "status": result.status.value,
        "artifacts": [{**asdict(item), "kind": item.kind.value} for item in result.artifacts],
        "verification": [asdict(item) for item in result.verification],
        "progress": [asdict(item) for item in result.progress],
        "error": result.error,
        "rollback_performed": result.rollback_performed,
        "metadata": dict(result.metadata),
        "failure_fingerprint": result.failure_fingerprint,
    }


def _safe_relative_path(value: str) -> str:
    raw = value.replace("\\", "/").strip()
    path = Path(raw)
    if not raw or path.is_absolute() or ".." in path.parts:
        raise CodingRuntimeError(f"invalid relative path: {value}")
    return path.as_posix()


def _allowed_relative(relative: str, allowed: tuple[str, ...]) -> bool:
    path = Path(relative)
    for raw in allowed:
        normalized = Path(str(raw).replace("\\", "/"))
        if str(normalized) in {"", "."}:
            return True
        try:
            path.relative_to(normalized)
            return True
        except ValueError:
            continue
    return False


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _allowed_verification_argv(argv: tuple[str, ...]) -> tuple[str, ...]:
    if len(argv) < 3:
        raise CodingRuntimeError("verification command must use python -m <module>")
    first = Path(argv[0]).name.lower()
    if first in {"python", "python3", "python.exe", "python3.exe"} or Path(argv[0]).resolve() == Path(sys.executable).resolve():
        executable = sys.executable
    else:
        raise CodingRuntimeError("verification executable is not allowlisted")
    if argv[1] != "-m" or argv[2] not in {"pytest", "unittest", "compileall"}:
        raise CodingRuntimeError("verification module is not allowlisted")
    if len(argv) > 32:
        raise CodingRuntimeError("verification argv exceeds limit")
    return (executable, *argv[1:])


def _sanitized_env() -> dict[str, str]:
    allowed = {"PATH", "SYSTEMROOT", "WINDIR", "HOME", "USERPROFILE", "TMP", "TEMP", "PYTHONPATH", "LANG", "LC_ALL"}
    env = {key: value for key, value in os.environ.items() if key in allowed}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["AETHER_RUNTIME_NETWORK"] = "disabled"
    return env
