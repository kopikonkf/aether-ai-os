"""Bounded local runtime adapter for projected Aether skills."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Mapping

from aether.contracts.capabilities import RuntimeSkillProfile, SkillProjectionReceipt
from aether.contracts.event_types import EventType
from aether.contracts.runtime import RuntimeAdapter, RuntimeCommand, RuntimeResult
from aether.contracts.skills import SkillLifecycleStatus, SkillRecord, SkillUsageEvent, canonical_manifest_payload
from aether.events import EventBus
from aether.skills import SkillFactory, SkillFactoryBlocked, SQLiteSkillStore


class SkillRuntimeError(RuntimeError):
    pass


class LocalProjectedSkillRuntimeAdapter(RuntimeAdapter):
    """Projects and invokes deterministic ``template-v1`` skills.

    This adapter is intentionally narrow. It proves the runtime projection and
    invocation boundary without shell execution, ``eval``, network access, or
    runtime ownership of the canonical skill registry.
    """

    def __init__(
        self,
        store: SQLiteSkillStore,
        factory: SkillFactory,
        projection_root: Path,
        *,
        event_bus: EventBus | None = None,
        routing_key: str = "skill-template",
    ) -> None:
        self.store = store
        self.factory = factory
        self.projection_root = projection_root.resolve()
        self.projection_root.mkdir(parents=True, exist_ok=True)
        self.event_bus = event_bus
        self.routing_key = routing_key

    @property
    def adapter_id(self) -> str:
        return "runtime.skill.local-template"

    @property
    def profile(self) -> RuntimeSkillProfile:
        return RuntimeSkillProfile(
            routing_key=self.routing_key,
            adapter_id=self.adapter_id,
            operations=("skill.execute",),
            runtime_features=("aether.template-v1", "json-io"),
            supported_side_effects=(),
            healthy=True,
            priority=10,
            metadata={"isolation": "no-shell-deterministic-template", "canonical_registry": False},
        )

    async def capabilities(self) -> set[str]:
        return {"skill.execute"}

    async def health(self) -> Mapping[str, Any]:
        return {
            "ok": True,
            "adapter_id": self.adapter_id,
            "routing_key": self.routing_key,
            "projection_root": str(self.projection_root),
            "features": list(self.profile.runtime_features),
        }

    async def execute(self, command: RuntimeCommand) -> RuntimeResult:
        if command.command != "skill.execute":
            return RuntimeResult(False, error=f"Unsupported skill command: {command.command}", metadata={"error_type": "CommandDenied"})
        started = time.monotonic()
        arguments = dict(command.arguments)
        skill_id = str(arguments.get("skill_id") or "")
        if not skill_id:
            return RuntimeResult(False, error="skill.execute requires skill_id", metadata={"error_type": "InvalidArguments"})
        record: SkillRecord | None = None
        projection: SkillProjectionReceipt | None = None
        result: RuntimeResult
        try:
            record = self.store.get_record(skill_id)
            self._validate_record(record, arguments)
            projection = await self.project(record)
            payload = dict(arguments.get("input") or {})
            input_errors = _validate_schema(payload, record.manifest.usage.input_schema, "input")
            if input_errors:
                raise SkillRuntimeError("; ".join(input_errors))
            output = self._invoke_template(record, payload)
            output_errors = _validate_schema(output, record.manifest.usage.output_schema, "output")
            if output_errors:
                raise SkillRuntimeError("; ".join(output_errors))
            result = RuntimeResult(True, output=output, metadata={
                "adapter_id": self.adapter_id,
                "runtime_routing_key": self.routing_key,
                "skill_id": record.skill_id,
                "skill_name": record.manifest.name,
                "skill_version": record.manifest.version,
                "artifact_hash": record.artifact_hash,
                "projection_id": projection.projection_id,
                "projection_path": projection.projection_path,
                "result_verified": True,
                "shell": False,
            })
        except Exception as exc:
            result = RuntimeResult(False, error=f"{type(exc).__name__}: {exc}", metadata={
                "adapter_id": self.adapter_id,
                "runtime_routing_key": self.routing_key,
                "skill_id": skill_id,
                "error_type": type(exc).__name__,
                "projection_id": projection.projection_id if projection else None,
                "result_verified": False,
            })
        duration = time.monotonic() - started
        if record is not None:
            runtime_failure_fingerprint = None
            if not result.ok:
                raw_failure = f"{record.skill_id}|{arguments.get('capability')}|{result.error or ''}"
                runtime_failure_fingerprint = hashlib.sha256(raw_failure.encode("utf-8")).hexdigest()
            usage_event = SkillUsageEvent(
                skill_id=record.skill_id,
                runtime_id=self.adapter_id,
                success=result.ok,
                duration_seconds=duration,
                session_id=str(arguments.get("session_id") or command.correlation_id or "") or None,
                event_id=str(arguments.get("route_event_id") or "") or None,
                error_fingerprint=runtime_failure_fingerprint,
                metadata={
                    "capability": arguments.get("capability"),
                    "requirement_id": arguments.get("requirement_id"),
                    "projection_id": projection.projection_id if projection else None,
                    "result_verified": bool(result.metadata.get("result_verified")),
                    "invocation_rejected": record.lifecycle_status != SkillLifecycleStatus.ACTIVE,
                },
            )
            try:
                usage = self.factory.record_usage(usage_event)
            except SkillFactoryBlocked:
                usage = self.store.add_usage(usage_event)
            except Exception as exc:
                return RuntimeResult(False, error=f"TelemetryPersistenceError: {exc}", metadata={
                    **dict(result.metadata),
                    "error_type": "TelemetryPersistenceError",
                    "original_ok": result.ok,
                })
            result = RuntimeResult(result.ok, result.output, result.error, {
                **dict(result.metadata),
                "usage_id": usage.usage_id,
                "runtime_failure_fingerprint": runtime_failure_fingerprint,
            })
        event_type = EventType.SKILL_EXECUTION_VERIFIED if result.ok else EventType.SKILL_EXECUTION_FAILED
        self._emit(event_type, {
            "skill_id": skill_id,
            "ok": result.ok,
            "error": result.error,
            "duration_seconds": duration,
            "projection_id": projection.projection_id if projection else None,
        }, severity="info" if result.ok else "error", correlation_id=command.correlation_id)
        return result

    async def project(self, record: SkillRecord) -> SkillProjectionReceipt:
        self._emit(EventType.SKILL_PROJECTION_REQUESTED, {
            "skill_id": record.skill_id,
            "artifact_hash": record.artifact_hash,
            "runtime_adapter_id": self.adapter_id,
        })
        skill_dir = self.projection_root / _slug(record.manifest.name) / record.skill_id
        skill_dir.mkdir(parents=True, exist_ok=True)
        path = skill_dir / f"{record.artifact_hash}.json"
        payload = {
            "authority": "projection_only",
            "canonical_skill_id": record.skill_id,
            "artifact_hash": record.artifact_hash,
            "runtime_adapter_id": self.adapter_id,
            "manifest": canonical_manifest_payload(record.manifest),
        }
        encoded = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True).encode("utf-8")
        projection_hash = hashlib.sha256(encoded).hexdigest()
        if not path.exists() or path.read_bytes() != encoded:
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(encoded)
            os.replace(temporary, path)
        receipt = SkillProjectionReceipt(
            skill_id=record.skill_id,
            artifact_hash=record.artifact_hash,
            runtime_adapter_id=self.adapter_id,
            projection_path=str(path),
            projection_hash=projection_hash,
            metadata={"authority": "projection_only", "retention": "no-automatic-deletion"},
        )
        self._emit(EventType.SKILL_PROJECTED, {
            "skill_id": record.skill_id,
            "projection_id": receipt.projection_id,
            "projection_hash": projection_hash,
            "projection_path": str(path),
        })
        return receipt

    def _validate_record(self, record: SkillRecord, arguments: Mapping[str, Any]) -> None:
        if record.lifecycle_status != SkillLifecycleStatus.ACTIVE:
            raise SkillRuntimeError(f"skill is not active: {record.lifecycle_status.value}")
        expected_hash = str(arguments.get("artifact_hash") or "")
        if expected_hash != record.artifact_hash:
            raise SkillRuntimeError("skill artifact hash does not match canonical registry")
        capability = str(arguments.get("capability") or "")
        if capability not in record.manifest.usage.capabilities:
            raise SkillRuntimeError(f"skill does not provide capability: {capability}")
        missing = set(record.manifest.usage.runtime_requirements) - set(self.profile.runtime_features)
        if missing:
            raise SkillRuntimeError("runtime missing required features: " + ", ".join(sorted(missing)))
        if record.manifest.usage.side_effects:
            raise SkillRuntimeError("local template runtime does not support side effects")

    @staticmethod
    def _invoke_template(record: SkillRecord, payload: Mapping[str, Any]) -> Any:
        execution = dict(record.manifest.metadata.get("execution") or {})
        if execution.get("kind") != "template-v1":
            raise SkillRuntimeError("skill execution kind is not supported by this runtime")
        template = str(execution.get("template") or "")
        if not template:
            raise SkillRuntimeError("template-v1 skill requires a non-empty template")
        try:
            rendered = template.format_map(_StrictFormatMap(payload))
        except KeyError as exc:
            raise SkillRuntimeError(f"missing template input: {exc.args[0]}") from exc
        output_mode = str(execution.get("output_mode") or "object")
        return rendered if output_mode == "string" else {"text": rendered}

    def _emit(self, event_type: EventType, payload: Mapping[str, Any], *, severity: str = "info", correlation_id: str | None = None) -> None:
        if self.event_bus is not None:
            self.event_bus.emit(
                event_type,
                actor=self.adapter_id,
                payload=dict(payload),
                severity=severity,
                correlation_id=correlation_id,
            )


class _StrictFormatMap(dict):
    def __missing__(self, key: str):
        raise KeyError(key)


def _slug(value: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-")
    return cleaned or "skill"


def _validate_schema(value: Any, schema: Mapping[str, Any], path: str) -> tuple[str, ...]:
    if not schema:
        return ()
    errors: list[str] = []
    expected = schema.get("type")
    type_map = {
        "object": dict,
        "array": list,
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "null": type(None),
    }
    if expected in type_map and not isinstance(value, type_map[expected]):
        return (f"{path} must be {expected}",)
    if expected == "object" and isinstance(value, Mapping):
        for key in schema.get("required") or []:
            if key not in value:
                errors.append(f"{path}.{key} is required")
        for key, child in (schema.get("properties") or {}).items():
            if key in value and isinstance(child, Mapping):
                errors.extend(_validate_schema(value[key], child, f"{path}.{key}"))
    if expected == "array" and isinstance(value, list) and isinstance(schema.get("items"), Mapping):
        for index, item in enumerate(value):
            errors.extend(_validate_schema(item, schema["items"], f"{path}[{index}]"))
    return tuple(errors)
