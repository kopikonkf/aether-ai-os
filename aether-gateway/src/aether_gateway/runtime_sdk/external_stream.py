"""Generic external coding-runtime adapter using Aether JSONL Streaming Protocol v1."""
from __future__ import annotations

import asyncio
import difflib
import hashlib
import json
import os
import shutil
import sys
import time
from dataclasses import asdict, dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from aether.contracts import (
    AETHER_CODING_STREAM_PROTOCOL,
    ExternalRuntimeHandshake,
    RuntimeCommand,
    RuntimeGeneratedPatch,
    RuntimeResult,
    RuntimeStreamFrameType,
)
from aether.contracts.coding_runtime import (
    CodingArtifact,
    CodingArtifactKind,
    CodingExecutionStatus,
    CodingTaskResult,
    RuntimeDescriptor,
    RuntimeHealthStatus,
    RuntimeProgress,
    VerificationReceipt,
    coding_task_fingerprint,
)
from aether.contracts.event_types import EventType
from aether.events import EventBus
from aether.utils.ids import new_id

from .sdk import CodingRuntimeAdapterBase
from .store import RuntimeTelemetryStore


class ExternalRuntimeProtocolError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExternalRuntimeProtocolPolicy:
    protocol: str
    handshake_timeout_seconds: float
    task_timeout_seconds: float
    maximum_frames: int
    maximum_frame_bytes: int
    maximum_stdout_bytes: int
    maximum_stderr_bytes: int
    allowed_frame_types: tuple[str, ...]
    maximum_files: int
    maximum_total_bytes: int
    maximum_diff_chars: int
    require_before_hash: bool
    reject_unknown_frame_types: bool
    reject_out_of_order_sequence: bool

    @classmethod
    def load(cls) -> "ExternalRuntimeProtocolPolicy":
        path = files("aether.runtimes").joinpath("external_runtime_protocol.yaml")
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        protocol = data["protocol"]
        patch = data["patch_ingestion"]
        streaming = data["streaming"]
        return cls(
            protocol=str(protocol["name"]),
            handshake_timeout_seconds=float(protocol["handshake_timeout_seconds"]),
            task_timeout_seconds=float(protocol["task_timeout_seconds"]),
            maximum_frames=max(1, int(protocol["maximum_frames"])),
            maximum_frame_bytes=max(1024, int(protocol["maximum_frame_bytes"])),
            maximum_stdout_bytes=max(1024, int(protocol["maximum_stdout_bytes"])),
            maximum_stderr_bytes=max(1024, int(protocol["maximum_stderr_bytes"])),
            allowed_frame_types=tuple(str(item) for item in protocol["allowed_frame_types"]),
            maximum_files=max(1, int(patch["maximum_files"])),
            maximum_total_bytes=max(1, int(patch["maximum_total_bytes"])),
            maximum_diff_chars=max(1000, int(patch["maximum_diff_chars"])),
            require_before_hash=bool(patch["require_before_sha256_for_existing_files"]),
            reject_unknown_frame_types=bool(streaming["reject_unknown_frame_types"]),
            reject_out_of_order_sequence=bool(streaming["reject_out_of_order_sequence"]),
        )


class ExternalStreamingCodingRuntimeAdapter(CodingRuntimeAdapterBase):
    """Run a coding body as an external process and ingest its streamed patches.

    The external process never receives production authority. It operates on a
    bounded staging copy and emits JSONL frames. Aether independently validates
    and verifies the resulting patch before atomically applying it to production.
    """

    OPERATION = "coding.task.execute"

    def __init__(
        self,
        argv: Sequence[str],
        state_root: Path,
        telemetry: RuntimeTelemetryStore,
        *,
        allowed_workspace_roots: Sequence[Path],
        event_bus: EventBus | None = None,
        routing_key: str = "runtime://coding/external-jsonl-reference",
        adapter_id: str = "runtime.coding.external-jsonl-reference",
        display_name: str = "Aether External JSONL Coding Runtime",
        priority: int = 10,
        policy: ExternalRuntimeProtocolPolicy | None = None,
        max_workspace_files: int = 5000,
        max_workspace_bytes: int = 52_428_800,
        runtime_env: Mapping[str, str] | None = None,
        environment_policy_id: str = "aether.external-runtime.default",
    ) -> None:
        if not argv or any(not str(item).strip() for item in argv):
            raise ExternalRuntimeProtocolError("external runtime argv must be a non-empty argv sequence")
        self.argv = tuple(str(item) for item in argv)
        self.state_root = state_root.expanduser().resolve()
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.telemetry = telemetry
        self.allowed_workspace_roots = tuple(Path(item).expanduser().resolve() for item in allowed_workspace_roots)
        if not self.allowed_workspace_roots:
            raise ExternalRuntimeProtocolError("at least one allowed workspace root is required")
        self.event_bus = event_bus
        self.routing_key = routing_key
        self._adapter_id = adapter_id
        self.display_name = display_name
        self.priority = int(priority)
        self.policy = policy or ExternalRuntimeProtocolPolicy.load()
        self.max_workspace_files = max(1, int(max_workspace_files))
        self.max_workspace_bytes = max(1024, int(max_workspace_bytes))
        self.runtime_env = {str(k): str(v) for k, v in dict(runtime_env or {}).items() if str(k).strip()}
        self.environment_policy_id = str(environment_policy_id)
        self._handshake: ExternalRuntimeHandshake | None = None

    @property
    def adapter_id(self) -> str:
        return self._adapter_id

    @property
    def descriptor(self) -> RuntimeDescriptor:
        handshake = self._handshake
        return RuntimeDescriptor(
            routing_key=self.routing_key,
            adapter_id=self.adapter_id,
            display_name=handshake.display_name if handshake else self.display_name,
            operations=handshake.operations if handshake else (self.OPERATION,),
            capabilities=handshake.capabilities if handshake else (
                "coding.edit", "coding.verify", "coding.patch-generation", "coding.artifact-return",
            ),
            runtime_features=handshake.runtime_features if handshake else (
                "external-cli", "jsonl-stream-v1", "runtime-generated-patch",
                "independent-verification", "workspace-binding", "progress-events",
                "bounded-artifacts", "verification-receipts", "no-shell",
            ),
            health_status=(RuntimeHealthStatus.DEGRADED if handshake and bool(handshake.metadata.get("degraded")) else RuntimeHealthStatus.HEALTHY) if handshake else RuntimeHealthStatus.DEGRADED,
            priority=self.priority,
            metadata={
                "authority": "body_only",
                "external_process": True,
                "protocol": self.policy.protocol,
                "shell": False,
                "argv_executable": Path(self.argv[0]).name,
                "environment_policy_id": self.environment_policy_id,
                "explicit_environment_names": sorted(self.runtime_env),
                **({
                    "runtime_id": handshake.runtime_id,
                    "runtime_version": handshake.runtime_version,
                    "handshake_fingerprint": handshake.fingerprint(),
                    "handshake_metadata": dict(handshake.metadata),
                } if handshake else {}),
            },
        )

    async def capabilities(self) -> set[str]:
        return {self.OPERATION}

    async def discover_descriptor(self) -> RuntimeDescriptor:
        await self._perform_handshake()
        return self.descriptor

    async def health(self) -> Mapping[str, Any]:
        try:
            handshake = await self._perform_handshake()
            return {
                "ok": True,
                "degraded": bool(handshake.metadata.get("degraded")),
                "adapter_id": self.adapter_id,
                "routing_key": self.routing_key,
                "protocol": handshake.protocol,
                "runtime_id": handshake.runtime_id,
                "runtime_version": handshake.runtime_version,
                "capabilities": list(handshake.capabilities),
                "features": list(handshake.runtime_features),
                "handshake_fingerprint": handshake.fingerprint(),
                "shell": False,
            }
        except Exception as exc:
            return {
                "ok": False,
                "adapter_id": self.adapter_id,
                "routing_key": self.routing_key,
                "error": f"{type(exc).__name__}: {exc}",
            }

    async def execute(self, command: RuntimeCommand) -> RuntimeResult:
        if command.command != self.OPERATION:
            return RuntimeResult(False, error=f"Unsupported coding command: {command.command}", metadata={"error_type": "CommandDenied"})
        started = time.monotonic()
        task_data = dict(command.arguments.get("task") or {})
        binding = dict(command.arguments.get("workspace_binding") or {})
        task_id = str(task_data.get("task_id") or new_id("coding-task"))
        workspace_id = str(task_data.get("workspace_id") or "")
        session_id = str(task_data.get("session_id") or "")
        progress: list[RuntimeProgress] = []
        receipts: list[VerificationReceipt] = []
        artifacts: list[CodingArtifact] = []
        rollback_performed = False
        runtime_frames = 0
        runtime_logs: list[str] = []
        process_exit_code: int | None = None
        run_root = self.state_root / "runs" / task_id
        staging = run_root / "workspace"
        transcript = run_root / "stream.jsonl"
        try:
            handshake = await self._perform_handshake()
            root = self._validate_binding(binding, workspace_id, session_id)
            if run_root.exists():
                raise ExternalRuntimeProtocolError("task ID already has external runtime lineage; replay is denied")
            run_root.mkdir(parents=True, exist_ok=False)
            self._copy_workspace(root, staging)
            self._progress(progress, task_id, "prepared", "Bounded staging workspace prepared for external runtime.", 1, 5.0, command.correlation_id)

            driver_id = str(handshake.metadata.get("driver_id") or handshake.runtime_id)
            self._emit(EventType.RUNTIME_DRIVER_TRANSLATION_STARTED, {
                "task_id": task_id,
                "driver_id": driver_id,
                "runtime_id": handshake.runtime_id,
                "runtime_version": handshake.runtime_version,
                "protocol": handshake.protocol,
                "environment_policy_id": self.environment_policy_id,
            }, correlation_id=command.correlation_id)

            request = {
                "type": "task.start",
                "protocol": self.policy.protocol,
                "task": task_data,
                "workspace": {
                    "root": str(staging),
                    "allowed_relative_paths": list(binding.get("allowed_relative_paths") or (".",)),
                    "writable": bool(binding.get("writable", False)),
                    "authority": "staging_only",
                },
                "limits": {
                    "maximum_files": min(self.policy.maximum_files, int(task_data.get("max_artifacts") or self.policy.maximum_files)),
                    "maximum_total_bytes": min(self.policy.maximum_total_bytes, int(task_data.get("max_total_bytes") or self.policy.maximum_total_bytes)),
                    "maximum_frame_bytes": min(self.policy.maximum_frame_bytes, handshake.max_frame_bytes),
                },
            }
            (run_root / "request.json").write_text(json.dumps(request, indent=2, sort_keys=True), encoding="utf-8")
            patches, frame_count, runtime_logs, process_exit_code = await self._run_external_process(
                request, task_id, staging, transcript, progress, command.correlation_id,
                timeout=min(float(command.timeout_seconds or self.policy.task_timeout_seconds), self.policy.task_timeout_seconds),
            )
            runtime_frames = frame_count
            self._progress(progress, task_id, "patch-received", f"Received {len(patches)} runtime-generated patch artifact(s).", len(progress) + 1, 85.0, command.correlation_id)
            patch_state = self._ingest_patches(staging, root, binding, patches, task_data, command.correlation_id)
            self._progress(progress, task_id, "patch-staged", "Runtime-generated patch was validated and applied only to staging.", len(progress) + 1, 88.0, command.correlation_id)

            commands = tuple(dict(item) for item in task_data.get("verification_commands") or ())
            if patch_state and not commands:
                raise ExternalRuntimeProtocolError("runtime-generated patch requires independent verification commands")
            for index, raw in enumerate(commands, start=1):
                receipt = await self._run_verification(staging, raw)
                receipts.append(receipt)
                self._progress(
                    progress, task_id, "verification",
                    f"Independent verification {index}/{len(commands)}: {receipt.label} {'passed' if receipt.ok else 'failed'}.",
                    len(progress) + 1, 88.0 + (10.0 * index / max(1, len(commands))), command.correlation_id,
                    metadata={"receipt_id": receipt.receipt_id, "ok": receipt.ok, "independent": True},
                )
                if not receipt.ok:
                    raise ExternalRuntimeProtocolError(f"independent verification failed: {receipt.label}")

            try:
                artifacts = self._apply_to_production(root, patch_state, run_root / "production-backup", command.correlation_id)
            except Exception:
                rollback_performed = self._rollback_production(patch_state)
                raise
            self._progress(progress, task_id, "completed", "Verified external patch atomically applied to production workspace.", len(progress) + 1, 100.0, command.correlation_id)
            result = CodingTaskResult(
                task_id=task_id,
                runtime_adapter_id=self.adapter_id,
                ok=True,
                status=CodingExecutionStatus.COMPLETED,
                artifacts=tuple(artifacts),
                verification=tuple(receipts),
                progress=tuple(progress),
                rollback_performed=False,
                metadata={
                    "workspace_id": workspace_id,
                    "session_id": session_id,
                    "result_verified": True,
                    "external_protocol": handshake.protocol,
                    "external_runtime_id": handshake.runtime_id,
                    "external_runtime_version": handshake.runtime_version,
                    "runtime_frame_count": runtime_frames,
                    "runtime_logs": runtime_logs[-20:],
                    "patch_trusted": False,
                    "independent_verification": True,
                    "process_exit_code": process_exit_code,
                },
            )
            duration = time.monotonic() - started
            invocation_id = self.telemetry.record_invocation(
                task_id=task_id, adapter_id=self.adapter_id, workspace_id=workspace_id,
                session_id=session_id, ok=True, status=result.status.value,
                duration_seconds=duration, artifact_count=len(artifacts),
                verification_count=len(receipts), failure_fingerprint=None,
                payload={"result": _result_payload(result), "transcript": str(transcript)},
            )
            self._emit(EventType.RUNTIME_DRIVER_TRANSLATION_COMPLETED, {
                "task_id": task_id,
                "driver_id": str(handshake.metadata.get("driver_id") or handshake.runtime_id),
                "runtime_id": handshake.runtime_id,
                "runtime_version": handshake.runtime_version,
                "runtime_frame_count": runtime_frames,
                "artifact_count": len(artifacts),
                "verification_count": len(receipts),
            }, correlation_id=command.correlation_id)
            self._emit(EventType.CODING_TASK_VERIFIED, {
                "task_id": task_id,
                "invocation_id": invocation_id,
                "artifact_count": len(artifacts),
                "verification_count": len(receipts),
                "external_runtime_id": handshake.runtime_id,
                "runtime_frame_count": runtime_frames,
            }, correlation_id=command.correlation_id)
            return RuntimeResult(True, output=_result_payload(result), metadata={
                "adapter_id": self.adapter_id,
                "runtime_routing_key": self.routing_key,
                "invocation_id": invocation_id,
                "result_verified": True,
                "artifact_count": len(artifacts),
                "verification_count": len(receipts),
                "workspace_id": workspace_id,
                "session_id": session_id,
                "external_protocol": handshake.protocol,
                "external_runtime_id": handshake.runtime_id,
                "external_runtime_version": handshake.runtime_version,
                "runtime_frame_count": runtime_frames,
                "patch_trusted": False,
                "independent_verification": True,
                "shell": False,
            })
        except Exception as exc:
            handshake_for_failure = self._handshake
            if handshake_for_failure is not None:
                self._emit(EventType.RUNTIME_DRIVER_TRANSLATION_FAILED, {
                    "task_id": task_id,
                    "driver_id": str(handshake_for_failure.metadata.get("driver_id") or handshake_for_failure.runtime_id),
                    "runtime_id": handshake_for_failure.runtime_id,
                    "runtime_version": handshake_for_failure.runtime_version,
                    "runtime_frame_count": runtime_frames,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }, severity="error", correlation_id=command.correlation_id)
            if isinstance(exc, ExternalRuntimeProtocolError):
                self._emit(EventType.RUNTIME_PATCH_REJECTED, {
                    "task_id": task_id,
                    "error": str(exc),
                    "runtime_frame_count": runtime_frames,
                }, severity="error", correlation_id=command.correlation_id)
            duration = time.monotonic() - started
            failure = coding_task_fingerprint(_minimal_task(task_data), error=f"{type(exc).__name__}: {exc}")
            self._progress(progress, task_id, "failed", f"External coding runtime failed: {type(exc).__name__}: {exc}", len(progress) + 1, None, command.correlation_id,
                           metadata={"failure_fingerprint": failure})
            invocation_id = self.telemetry.record_invocation(
                task_id=task_id, adapter_id=self.adapter_id, workspace_id=workspace_id,
                session_id=session_id, ok=False, status=CodingExecutionStatus.FAILED.value,
                duration_seconds=duration, artifact_count=len(artifacts),
                verification_count=len(receipts), failure_fingerprint=failure,
                payload={
                    "error": f"{type(exc).__name__}: {exc}",
                    "rollback_performed": rollback_performed,
                    "runtime_frame_count": runtime_frames,
                    "process_exit_code": process_exit_code,
                    "transcript": str(transcript),
                },
            )
            self._emit(EventType.CODING_TASK_FAILED, {
                "task_id": task_id,
                "invocation_id": invocation_id,
                "error": f"{type(exc).__name__}: {exc}",
                "failure_fingerprint": failure,
                "rollback_performed": rollback_performed,
            }, severity="error", correlation_id=command.correlation_id)
            return RuntimeResult(False, error=f"{type(exc).__name__}: {exc}", metadata={
                "adapter_id": self.adapter_id,
                "runtime_routing_key": self.routing_key,
                "invocation_id": invocation_id,
                "failure_fingerprint": failure,
                "rollback_performed": rollback_performed,
                "runtime_frame_count": runtime_frames,
                "process_exit_code": process_exit_code,
                "shell": False,
                "error_type": type(exc).__name__,
            })
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)

    def _external_env(self) -> dict[str, str]:
        env = _sanitized_env()
        env.update(self.runtime_env)
        return env

    async def _perform_handshake(self) -> ExternalRuntimeHandshake:
        if self._handshake is not None:
            return self._handshake
        proc = await asyncio.create_subprocess_exec(
            *self.argv, "--aether-handshake",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._external_env(),
            limit=self.policy.maximum_frame_bytes + 1024,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.policy.handshake_timeout_seconds)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise ExternalRuntimeProtocolError("external runtime handshake timed out")
        if len(stdout) > self.policy.maximum_frame_bytes:
            raise ExternalRuntimeProtocolError("external runtime handshake exceeds frame limit")
        if len(stderr) > self.policy.maximum_stderr_bytes:
            raise ExternalRuntimeProtocolError("external runtime handshake stderr exceeds limit")
        if proc.returncode != 0:
            raise ExternalRuntimeProtocolError(f"external runtime handshake failed with exit code {proc.returncode}: {stderr.decode(errors='replace')[-2000:]}")
        lines = [line for line in stdout.decode("utf-8", errors="strict").splitlines() if line.strip()]
        if len(lines) != 1:
            raise ExternalRuntimeProtocolError("external runtime handshake must return exactly one JSON object")
        try:
            data = json.loads(lines[0])
        except json.JSONDecodeError as exc:
            raise ExternalRuntimeProtocolError("external runtime handshake is not valid JSON") from exc
        handshake = _parse_handshake(data)
        if handshake.protocol != self.policy.protocol or handshake.protocol != AETHER_CODING_STREAM_PROTOCOL:
            raise ExternalRuntimeProtocolError(f"unsupported external runtime protocol: {handshake.protocol}")
        if self.OPERATION not in handshake.operations:
            raise ExternalRuntimeProtocolError("external runtime does not advertise coding.task.execute")
        if handshake.max_frame_bytes < 1024 or handshake.max_patch_files < 1:
            raise ExternalRuntimeProtocolError("external runtime advertised invalid limits")
        self._handshake = handshake
        self._emit(EventType.RUNTIME_PROTOCOL_HANDSHAKE, {
            "adapter_id": self.adapter_id,
            "routing_key": self.routing_key,
            "protocol": handshake.protocol,
            "runtime_id": handshake.runtime_id,
            "runtime_version": handshake.runtime_version,
            "handshake_fingerprint": handshake.fingerprint(),
        })
        return handshake

    async def _run_external_process(
        self,
        request: Mapping[str, Any],
        task_id: str,
        staging: Path,
        transcript: Path,
        progress: list[RuntimeProgress],
        correlation_id: str | None,
        *,
        timeout: float,
    ) -> tuple[list[RuntimeGeneratedPatch], int, list[str], int]:
        proc = await asyncio.create_subprocess_exec(
            *self.argv, "--aether-run",
            cwd=str(staging),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._external_env(),
            limit=self.policy.maximum_frame_bytes + 1024,
        )
        self._emit(EventType.RUNTIME_EXTERNAL_PROCESS_STARTED, {
            "task_id": task_id,
            "adapter_id": self.adapter_id,
            "protocol": self.policy.protocol,
        }, correlation_id=correlation_id)
        assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None
        payload = (json.dumps(dict(request), sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
        proc.stdin.write(payload)
        await proc.stdin.drain()
        proc.stdin.close()
        stderr_task = asyncio.create_task(_read_limited(proc.stderr, self.policy.maximum_stderr_bytes))
        patches: list[RuntimeGeneratedPatch] = []
        logs: list[str] = []
        frame_count = 0
        stdout_bytes = 0
        last_runtime_sequence = -1
        completed = False
        transcript.parent.mkdir(parents=True, exist_ok=True)
        caught: Exception | None = None
        exit_code: int | None = None
        try:
            async with asyncio.timeout(timeout):
                with transcript.open("w", encoding="utf-8") as output:
                    while True:
                        try:
                            line = await proc.stdout.readline()
                        except (ValueError, asyncio.LimitOverrunError) as exc:
                            raise ExternalRuntimeProtocolError("external runtime frame exceeds stream reader limit") from exc
                        if not line:
                            break
                        stdout_bytes += len(line)
                        if stdout_bytes > self.policy.maximum_stdout_bytes:
                            raise ExternalRuntimeProtocolError("external runtime stdout exceeds limit")
                        if len(line) > self.policy.maximum_frame_bytes:
                            raise ExternalRuntimeProtocolError("external runtime frame exceeds byte limit")
                        frame_count += 1
                        if frame_count > self.policy.maximum_frames:
                            raise ExternalRuntimeProtocolError("external runtime frame count exceeds limit")
                        text = line.decode("utf-8", errors="strict").strip()
                        output.write(text + "\n")
                        try:
                            data = json.loads(text)
                        except json.JSONDecodeError as exc:
                            raise ExternalRuntimeProtocolError("external runtime emitted malformed JSON frame") from exc
                        frame_type = str(data.get("type") or "")
                        if self.policy.reject_unknown_frame_types and frame_type not in self.policy.allowed_frame_types:
                            raise ExternalRuntimeProtocolError(f"external runtime emitted unknown frame type: {frame_type}")
                        if str(data.get("protocol") or "") != self.policy.protocol:
                            raise ExternalRuntimeProtocolError("external runtime frame protocol mismatch")
                        if str(data.get("task_id") or "") != task_id:
                            raise ExternalRuntimeProtocolError("external runtime frame task_id mismatch")
                        sequence = int(data.get("sequence", -1))
                        if self.policy.reject_out_of_order_sequence and sequence <= last_runtime_sequence:
                            raise ExternalRuntimeProtocolError("external runtime frame sequence is not strictly increasing")
                        last_runtime_sequence = sequence
                        frame_payload = dict(data.get("payload") or {})
                        self._emit(EventType.RUNTIME_STREAM_FRAME, {
                            "task_id": task_id,
                            "frame_type": frame_type,
                            "runtime_sequence": sequence,
                            "payload_keys": sorted(frame_payload),
                        }, correlation_id=correlation_id)
                        if frame_type in {RuntimeStreamFrameType.ACCEPTED.value, RuntimeStreamFrameType.PROGRESS.value}:
                            self._progress(
                                progress, task_id,
                                str(frame_payload.get("phase") or "runtime"),
                                str(frame_payload.get("message") or frame_type),
                                len(progress) + 1,
                                _optional_percent(frame_payload.get("percent")),
                                correlation_id,
                                metadata={"runtime_sequence": sequence, "external": True},
                            )
                        elif frame_type == RuntimeStreamFrameType.LOG.value:
                            logs.append(str(frame_payload.get("message") or "")[:2000])
                        elif frame_type == RuntimeStreamFrameType.PATCH.value:
                            patch = RuntimeGeneratedPatch(
                                path=str(frame_payload.get("path") or ""),
                                content=str(frame_payload.get("content") or ""),
                                before_sha256=str(frame_payload.get("before_sha256")) if frame_payload.get("before_sha256") is not None else None,
                                kind=str(frame_payload.get("kind") or "upsert"),
                                runtime_diff=str(frame_payload.get("diff") or "")[: self.policy.maximum_diff_chars],
                                metadata={"runtime_sequence": sequence, **dict(frame_payload.get("metadata") or {})},
                            )
                            patches.append(patch)
                            self._emit(EventType.RUNTIME_PATCH_RECEIVED, {
                                "task_id": task_id,
                                "path": patch.path,
                                "kind": patch.kind,
                                "runtime_sequence": sequence,
                                "content_bytes": len(patch.content.encode("utf-8")),
                            }, correlation_id=correlation_id)
                        elif frame_type == RuntimeStreamFrameType.ERROR.value:
                            raise ExternalRuntimeProtocolError(str(frame_payload.get("error") or "external runtime reported an error"))
                        elif frame_type == RuntimeStreamFrameType.COMPLETED.value:
                            if not bool(frame_payload.get("ok", True)):
                                raise ExternalRuntimeProtocolError(str(frame_payload.get("error") or "external runtime completed unsuccessfully"))
                            completed = True
                exit_code = await proc.wait()
        except TimeoutError:
            caught = ExternalRuntimeProtocolError(f"external runtime task timed out after {timeout:.1f}s")
        except Exception as exc:
            caught = exc
        finally:
            if proc.returncode is None:
                proc.kill()
            try:
                exit_code = await proc.wait()
            except Exception:
                pass
            try:
                stderr = await asyncio.wait_for(stderr_task, timeout=2.0)
            except Exception:
                stderr_task.cancel()
                stderr = b""
        self._emit(EventType.RUNTIME_EXTERNAL_PROCESS_EXITED, {
            "task_id": task_id,
            "adapter_id": self.adapter_id,
            "exit_code": exit_code,
            "frame_count": frame_count,
            "stderr_bytes": len(stderr),
        }, severity="info" if exit_code == 0 and caught is None else "error", correlation_id=correlation_id)
        if caught is not None:
            raise caught
        if exit_code != 0:
            raise ExternalRuntimeProtocolError(f"external runtime exited with code {exit_code}: {stderr.decode('utf-8', errors='replace')[-2000:]}")
        if not completed:
            raise ExternalRuntimeProtocolError("external runtime stream ended without task.completed")
        return patches, frame_count, logs, int(exit_code)

    def _validate_binding(self, binding: Mapping[str, Any], workspace_id: str, session_id: str) -> Path:
        if str(binding.get("workspace_id") or "") != workspace_id:
            raise ExternalRuntimeProtocolError("workspace binding ID mismatch")
        if str(binding.get("session_id") or "") != session_id:
            raise ExternalRuntimeProtocolError("workspace binding session mismatch")
        if not bool(binding.get("writable", False)):
            raise ExternalRuntimeProtocolError("workspace binding is read-only")
        root = Path(str(binding.get("root_path") or "")).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise ExternalRuntimeProtocolError("workspace root is not available")
        if not any(_is_relative_to(root, allowed) for allowed in self.allowed_workspace_roots):
            raise ExternalRuntimeProtocolError("workspace root is outside configured allowed roots")
        return root

    def _copy_workspace(self, root: Path, staging: Path) -> None:
        staging.mkdir(parents=True, exist_ok=False)
        count = 0
        total = 0
        excluded = {".git", ".aether", "__pycache__", ".venv", "node_modules"}
        for source in root.rglob("*"):
            relative = source.relative_to(root)
            if any(part in excluded for part in relative.parts):
                continue
            target = staging / relative
            if source.is_symlink():
                continue
            if source.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not source.is_file():
                continue
            count += 1
            size = source.stat().st_size
            total += size
            if count > self.max_workspace_files or total > self.max_workspace_bytes:
                raise ExternalRuntimeProtocolError("workspace staging copy exceeds configured bounds")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    def _ingest_patches(
        self,
        staging: Path,
        production: Path,
        binding: Mapping[str, Any],
        patches: Sequence[RuntimeGeneratedPatch],
        task_data: Mapping[str, Any],
        correlation_id: str | None,
    ) -> list[dict[str, Any]]:
        maximum_files = min(self.policy.maximum_files, max(1, int(task_data.get("max_artifacts") or self.policy.maximum_files)))
        maximum_bytes = min(self.policy.maximum_total_bytes, max(1, int(task_data.get("max_total_bytes") or self.policy.maximum_total_bytes)))
        if not patches:
            raise ExternalRuntimeProtocolError("external runtime completed without a patch")
        if len(patches) > maximum_files:
            raise ExternalRuntimeProtocolError("runtime-generated patch file count exceeds limit")
        total_bytes = sum(len(item.content.encode("utf-8")) for item in patches)
        if total_bytes > maximum_bytes:
            raise ExternalRuntimeProtocolError("runtime-generated patch bytes exceed limit")
        allowed = tuple(str(item) for item in binding.get("allowed_relative_paths") or (".",))
        seen: set[str] = set()
        state: list[dict[str, Any]] = []
        for patch in patches:
            relative = _safe_relative_path(patch.path)
            if relative in seen:
                raise ExternalRuntimeProtocolError(f"duplicate runtime patch path: {relative}")
            seen.add(relative)
            if patch.kind != "upsert":
                raise ExternalRuntimeProtocolError(f"unsupported runtime patch kind: {patch.kind}")
            if not _allowed_relative(relative, allowed):
                raise ExternalRuntimeProtocolError(f"runtime patch path is outside binding allowlist: {relative}")
            staged_target = (staging / relative).resolve()
            prod_target = (production / relative).resolve()
            if not _is_relative_to(staged_target, staging) or not _is_relative_to(prod_target, production):
                raise ExternalRuntimeProtocolError(f"runtime patch path traversal denied: {relative}")
            before = staged_target.read_bytes() if staged_target.exists() else None
            before_hash = hashlib.sha256(before).hexdigest() if before is not None else None
            if before is not None and self.policy.require_before_hash and not patch.before_sha256:
                raise ExternalRuntimeProtocolError(f"runtime patch missing before_sha256: {relative}")
            if patch.before_sha256 != before_hash:
                raise ExternalRuntimeProtocolError(f"runtime patch before_sha256 mismatch: {relative}")
            content = patch.content.encode("utf-8")
            staged_target.parent.mkdir(parents=True, exist_ok=True)
            temporary = staged_target.with_name(staged_target.name + ".aether-external-tmp")
            temporary.write_bytes(content)
            os.replace(temporary, staged_target)
            state.append({
                "relative": relative,
                "staged": staged_target,
                "production": prod_target,
                "before": before,
                "before_hash": before_hash,
                "after": content,
                "after_hash": hashlib.sha256(content).hexdigest(),
                "runtime_diff": patch.runtime_diff,
                "production_applied": False,
            })
        return state

    async def _run_verification(self, root: Path, raw: Mapping[str, Any]) -> VerificationReceipt:
        argv = _allowed_verification_argv(tuple(str(item) for item in raw.get("argv") or ()))
        timeout = min(300.0, max(1.0, float(raw.get("timeout_seconds", 120.0))))
        label = str(raw.get("label") or "verification")
        started = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_sanitized_env(),
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return VerificationReceipt(
                label, argv, False, None, "", f"timed out after {timeout:.1f}s", time.monotonic() - started,
                metadata={"timeout": True, "shell": False, "independent": True},
            )
        return VerificationReceipt(
            label=label,
            argv=argv,
            ok=proc.returncode == 0,
            exit_code=proc.returncode,
            stdout=stdout_b.decode("utf-8", errors="replace")[-16000:],
            stderr=stderr_b.decode("utf-8", errors="replace")[-16000:],
            duration_seconds=time.monotonic() - started,
            metadata={"shell": False, "independent": True, "workspace": "staging"},
        )

    def _apply_to_production(
        self,
        root: Path,
        state: list[dict[str, Any]],
        backup_root: Path,
        correlation_id: str | None,
    ) -> list[CodingArtifact]:
        backup_root.mkdir(parents=True, exist_ok=False)
        artifacts: list[CodingArtifact] = []
        for item in state:
            target: Path = item["production"]
            current = target.read_bytes() if target.exists() else None
            current_hash = hashlib.sha256(current).hexdigest() if current is not None else None
            if current_hash != item["before_hash"]:
                raise ExternalRuntimeProtocolError(f"production hash changed after runtime execution: {item['relative']}")
            if current is not None:
                backup = backup_root / item["relative"]
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_bytes(current)
                item["backup"] = backup
            else:
                item["backup"] = None
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + ".aether-external-apply")
            temporary.write_bytes(item["after"])
            os.replace(temporary, target)
            item["production_applied"] = True
            before_text = item["before"].decode("utf-8", errors="replace") if item["before"] is not None else ""
            after_text = item["after"].decode("utf-8", errors="replace")
            actual_diff = "".join(difflib.unified_diff(
                before_text.splitlines(keepends=True),
                after_text.splitlines(keepends=True),
                fromfile=f"a/{item['relative']}",
                tofile=f"b/{item['relative']}",
            ))[: self.policy.maximum_diff_chars]
            artifact = CodingArtifact(
                path=item["relative"],
                kind=CodingArtifactKind.MODIFIED if item["before"] is not None else CodingArtifactKind.CREATED,
                before_sha256=item["before_hash"],
                after_sha256=item["after_hash"],
                size_bytes=len(item["after"]),
                diff=actual_diff,
                metadata={
                    "authority": "verified_runtime_evidence",
                    "runtime_diff_matches": item["runtime_diff"] == actual_diff if item["runtime_diff"] else None,
                    "workspace_relative": True,
                    "independent_verification": True,
                },
            )
            artifacts.append(artifact)
            self._emit(EventType.RUNTIME_PATCH_APPLIED, {
                "path": artifact.path,
                "artifact_id": artifact.artifact_id,
                "before_sha256": artifact.before_sha256,
                "after_sha256": artifact.after_sha256,
            }, correlation_id=correlation_id)
            self._emit(EventType.CODING_ARTIFACT_RETURNED, {
                "artifact_id": artifact.artifact_id,
                "path": artifact.path,
                "kind": artifact.kind.value,
                "after_sha256": artifact.after_sha256,
                "size_bytes": artifact.size_bytes,
            }, correlation_id=correlation_id)
        return artifacts

    def _rollback_production(self, state: list[dict[str, Any]]) -> bool:
        performed = False
        for item in reversed(state):
            if not item.get("production_applied"):
                continue
            target: Path = item["production"]
            if item["before"] is None:
                if target.exists():
                    target.unlink()
            else:
                temporary = target.with_name(target.name + ".aether-external-rollback")
                temporary.write_bytes(item["before"])
                os.replace(temporary, target)
            performed = True
        return performed

    def _progress(
        self,
        sink: list[RuntimeProgress],
        task_id: str,
        phase: str,
        message: str,
        sequence: int,
        percent: float | None,
        correlation_id: str | None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        item = RuntimeProgress(
            task_id=task_id,
            phase=phase,
            message=message,
            sequence=sequence,
            percent=percent,
            metadata=dict(metadata or {}),
        )
        sink.append(item)
        self.telemetry.record_progress(item)
        self._emit(EventType.CODING_TASK_PROGRESS, asdict(item), correlation_id=correlation_id)

    def _emit(
        self,
        event_type: EventType,
        payload: Mapping[str, Any],
        *,
        severity: str = "info",
        correlation_id: str | None = None,
    ) -> None:
        if self.event_bus is not None:
            self.event_bus.emit(
                event_type,
                actor=self.adapter_id,
                payload=dict(payload),
                severity=severity,
                correlation_id=correlation_id,
            )


def _parse_handshake(data: Mapping[str, Any]) -> ExternalRuntimeHandshake:
    runtime = dict(data.get("runtime") or {})
    limits = dict(data.get("limits") or {})
    return ExternalRuntimeHandshake(
        protocol=str(data.get("protocol") or ""),
        runtime_id=str(runtime.get("id") or ""),
        runtime_version=str(runtime.get("version") or ""),
        display_name=str(runtime.get("display_name") or runtime.get("id") or "External Coding Runtime"),
        operations=tuple(str(item) for item in runtime.get("operations") or ()),
        capabilities=tuple(str(item) for item in runtime.get("capabilities") or ()),
        runtime_features=tuple(str(item) for item in runtime.get("features") or ()),
        max_frame_bytes=int(limits.get("max_frame_bytes") or 0),
        max_patch_files=int(limits.get("max_patch_files") or 0),
        metadata=dict(runtime.get("metadata") or {}),
    )


async def _read_limited(reader: asyncio.StreamReader, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await reader.read(8192)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            chunks.append(chunk[: max(0, limit - (total - len(chunk)))])
            break
        chunks.append(chunk)
    return b"".join(chunks)


def _optional_percent(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return None


def _minimal_task(data: Mapping[str, Any]):
    from aether.contracts.coding_runtime import CodingEdit, CodingTask, VerificationCommand
    return CodingTask(
        objective=str(data.get("objective") or "failed external coding task"),
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
        raise ExternalRuntimeProtocolError(f"invalid relative path: {value}")
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
        raise ExternalRuntimeProtocolError("verification command must use python -m <module>")
    first = Path(argv[0]).name.lower()
    if first in {"python", "python3", "python.exe", "python3.exe"} or Path(argv[0]).resolve() == Path(sys.executable).resolve():
        executable = sys.executable
    else:
        raise ExternalRuntimeProtocolError("verification executable is not allowlisted")
    if argv[1] != "-m" or argv[2] not in {"pytest", "unittest", "compileall"}:
        raise ExternalRuntimeProtocolError("verification module is not allowlisted")
    if len(argv) > 32:
        raise ExternalRuntimeProtocolError("verification argv exceeds limit")
    return (executable, *argv[1:])


def _sanitized_env() -> dict[str, str]:
    allowed = {
        "PATH", "SYSTEMROOT", "WINDIR", "HOME", "USERPROFILE", "TMP", "TEMP",
        "PYTHONPATH", "LANG", "LC_ALL", "PYTHONHOME",
    }
    env = {key: value for key, value in os.environ.items() if key in allowed}
    if env.get("PYTHONPATH"):
        base = Path.cwd()
        env["PYTHONPATH"] = os.pathsep.join(
            str((base / item).resolve()) if item and not Path(item).is_absolute() else item
            for item in env["PYTHONPATH"].split(os.pathsep)
        )
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["AETHER_EXTERNAL_RUNTIME"] = "1"
    return env
