"""Runtime driver pack discovery, conformance, reliability, and adapter construction."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from importlib.resources import files
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from aether.contracts import (
    AETHER_CODING_STREAM_PROTOCOL,
    RuntimeConformanceCheck,
    RuntimeConformanceReceipt,
    RuntimeConformanceState,
    RuntimeDriverAvailability,
    RuntimeDriverImplementation,
    RuntimeDriverManifest,
    RuntimeDriverStatus,
    RuntimeOperationsDriverSnapshot,
    RuntimeQuotaState,
)
from aether.contracts.event_types import EventType
from aether.events import EventBus

from aether_gateway.runtime_sdk.external_stream import ExternalStreamingCodingRuntimeAdapter
from aether_gateway.runtime_sdk.store import RuntimeTelemetryStore

from .conformance import (
    ConformanceGatedRuntimeAdapter,
    RuntimeConformanceError,
    RuntimeConformanceStore,
    executable_sha256,
    reliability_snapshot,
    stable_configuration_hash,
)


class RuntimeDriverPack:
    def __init__(
        self,
        state_root: Path,
        telemetry: RuntimeTelemetryStore,
        *,
        allowed_workspace_roots: Sequence[Path],
        event_bus: EventBus | None = None,
    ) -> None:
        self.state_root = state_root.expanduser().resolve()
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.telemetry = telemetry
        self.allowed_workspace_roots = tuple(Path(item).expanduser().resolve() for item in allowed_workspace_roots)
        self.event_bus = event_bus
        data = yaml.safe_load(files("aether.runtimes").joinpath("runtime_driver_pack.yaml").read_text(encoding="utf-8"))
        self.policy = data
        self._raw_by_id = {str(item["driver_id"]): dict(item) for item in data.get("drivers", [])}
        self.manifests = tuple(self._manifest(item) for item in data.get("drivers", []))
        self.conformance_store = RuntimeConformanceStore(self.state_root / "runtime-conformance.sqlite3")
        for item in self.manifests:
            item.validate()

    def _manifest(self, raw: Mapping[str, Any]) -> RuntimeDriverManifest:
        implementation = RuntimeDriverImplementation(str(raw["implementation"]))
        live = implementation == RuntimeDriverImplementation.LIVE
        return RuntimeDriverManifest(
            driver_id=str(raw["driver_id"]),
            display_name=str(raw["display_name"]),
            vendor=str(raw["vendor"]),
            implementation=implementation,
            protocol=AETHER_CODING_STREAM_PROTOCOL,
            routing_key=str(raw["routing_key"]),
            adapter_id=str(raw["adapter_id"]),
            executable_candidates=tuple(str(item) for item in raw.get("executable_candidates", ())),
            version_argv=tuple(str(item) for item in raw.get("version_argv", ("--version",))),
            operations=("coding.task.execute",) if live else (),
            capabilities=("coding.edit", "coding.verify", "coding.patch-generation", "coding.artifact-return") if live else (),
            runtime_features=(
                "external-cli", "jsonl-stream-v1", "vendor-driver-pack-v1", "vendor-driver-pack-v2", "vendor-driver-pack-v3", "generative-coding",
                "runtime-generated-patch", "independent-verification", "workspace-binding",
                "progress-events", "bounded-artifacts", "verification-receipts", "no-shell",
                "conformance-receipt-v1", "reliability-ranking-v1", "quota-classification-v1", "runtime-operations-console-v1",
            ) if live else (),
            supported_platforms=("linux", "darwin", "windows"),
            credential_env_names=tuple(str(item) for item in raw.get("credential_env_names", ())),
            priority=int(raw.get("priority", 100)),
            enabled_by_default=bool(raw.get("enabled_by_default", False)),
            metadata={
                "policy_id": str(self.policy.get("policy_id")),
                "translator_module": raw.get("translator_module"),
                "environment_policy_id": raw.get("environment_policy_id"),
                "default_model": raw.get("default_model"),
            },
        )

    def manifest(self, driver_id: str) -> RuntimeDriverManifest:
        for item in self.manifests:
            if item.driver_id == driver_id:
                return item
        raise KeyError(driver_id)

    def _executable(self, manifest: RuntimeDriverManifest) -> str | None:
        env_name = {
            "openai-codex-cli": "AETHER_CODEX_BIN",
            "opencode-cli": "AETHER_OPENCODE_BIN",
            "google-gemini-cli": "AETHER_GEMINI_BIN",
            "anthropic-claude-code": "AETHER_CLAUDE_BIN",
        }.get(manifest.driver_id)
        if env_name:
            configured = os.environ.get(env_name, "").strip()
            if configured:
                path = Path(configured).expanduser()
                if path.is_absolute():
                    return str(path.resolve()) if path.is_file() else None
                return shutil.which(configured)
        for candidate in manifest.executable_candidates:
            found = shutil.which(candidate)
            if found:
                return found
        return None

    def _probe_version(self, manifest: RuntimeDriverManifest, executable: str) -> tuple[str | None, str | None]:
        try:
            completed = subprocess.run(
                [executable, *manifest.version_argv],
                capture_output=True,
                text=True,
                timeout=float(self.policy.get("discovery", {}).get("version_timeout_seconds", 5)),
                check=False,
                env={
                    key: value for key, value in os.environ.items()
                    if key in {"PATH", "SYSTEMROOT", "WINDIR", "HOME", "USERPROFILE", "TMP", "TEMP", "LANG", "LC_ALL"}
                },
            )
        except Exception as exc:
            return None, f"version probe failed: {type(exc).__name__}: {exc}"
        if completed.returncode != 0:
            return None, f"version probe exited {completed.returncode}: {completed.stderr[-500:]}"
        version = completed.stdout.strip() or completed.stderr.strip()
        return (version[:200], None) if version else (None, "version probe returned empty output")

    def _auth_ready(self, manifest: RuntimeDriverManifest) -> tuple[bool, str]:
        if manifest.driver_id == "openai-codex-cli":
            if os.environ.get("OPENAI_API_KEY", "").strip():
                return True, "api-key"
            raw = os.environ.get("AETHER_CODEX_HOME", "").strip() or os.environ.get("CODEX_HOME", "").strip()
            root = Path(raw).expanduser() if raw else Path.home() / ".codex"
            if any((root / name).is_file() for name in ("auth.json", "credentials.json")):
                return True, "codex-home"
            return False, "missing-auth"
        if manifest.driver_id == "opencode-cli":
            key_path = os.environ.get("AETHER_OPENCODE_API_KEY_FILE", "").strip()
            if key_path:
                path = Path(key_path).expanduser()
                if path.is_file() and path.stat().st_size > 0:
                    return True, "api-key-file"
            auth_path = os.environ.get("AETHER_OPENCODE_AUTH_FILE", "").strip()
            if auth_path and Path(auth_path).expanduser().is_file():
                return True, "auth-file"
            return False, "missing-auth"
        if manifest.driver_id == "google-gemini-cli":
            key_path = os.environ.get("AETHER_GEMINI_API_KEY_FILE", "").strip()
            if key_path and Path(key_path).expanduser().is_file() and Path(key_path).expanduser().stat().st_size > 0:
                return True, "api-key-file"
            credential_path = os.environ.get("AETHER_GEMINI_CREDENTIALS_FILE", "").strip()
            if credential_path and Path(credential_path).expanduser().is_file():
                return True, "application-credentials-file"
            return False, "missing-auth"
        if manifest.driver_id == "anthropic-claude-code":
            key_path = os.environ.get("AETHER_CLAUDE_API_KEY_FILE", "").strip()
            if key_path and Path(key_path).expanduser().is_file() and Path(key_path).expanduser().stat().st_size > 0:
                return True, "api-key-file"
            raw = os.environ.get("AETHER_CLAUDE_CONFIG_DIR", "").strip() or os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
            root = Path(raw).expanduser() if raw else Path.home() / ".claude"
            if root.is_dir() and any(item.is_file() for item in root.iterdir()):
                return True, "claude-config-dir"
            return False, "missing-auth"
        return False, "unsupported-auth"

    def _configuration_payload(self, manifest: RuntimeDriverManifest) -> Mapping[str, Any]:
        raw = self._raw_by_id[manifest.driver_id]
        payload: dict[str, Any] = {
            "driver_id": manifest.driver_id,
            "protocol": manifest.protocol,
            "translator_module": raw.get("translator_module"),
            "environment_policy_id": raw.get("environment_policy_id"),
        }
        if manifest.driver_id == "opencode-cli":
            model = os.environ.get("AETHER_OPENCODE_MODEL", str(raw.get("default_model") or "opencode/north-mini-code-free")).strip()
            key_path = os.environ.get("AETHER_OPENCODE_API_KEY_FILE", "").strip()
            key_ref: Mapping[str, Any] | None = None
            if key_path:
                path = Path(key_path).expanduser()
                if path.is_file():
                    stat = path.stat()
                    key_ref = {"path": str(path.resolve()), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
            payload.update({"provider_id": "opencode-zen", "model_id": model, "credential_reference": key_ref})
        elif manifest.driver_id == "google-gemini-cli":
            model = os.environ.get("AETHER_GEMINI_MODEL", str(raw.get("default_model") or "gemini-2.5-flash")).strip()
            key_path = os.environ.get("AETHER_GEMINI_API_KEY_FILE", "").strip()
            credentials_path = os.environ.get("AETHER_GEMINI_CREDENTIALS_FILE", "").strip()
            payload.update({
                "provider_id": "google-gemini",
                "model_id": model,
                "credential_reference": self._credential_reference(key_path or credentials_path),
            })
        elif manifest.driver_id == "anthropic-claude-code":
            model = os.environ.get("AETHER_CLAUDE_MODEL", str(raw.get("default_model") or "sonnet")).strip()
            key_path = os.environ.get("AETHER_CLAUDE_API_KEY_FILE", "").strip()
            config_path = os.environ.get("AETHER_CLAUDE_CONFIG_DIR", "").strip() or os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
            payload.update({
                "provider_id": "anthropic",
                "model_id": model,
                "credential_reference": self._credential_reference(key_path or config_path),
            })
        elif manifest.driver_id == "openai-codex-cli":
            payload.update({
                "provider_id": "openai",
                "model_id": os.environ.get("AETHER_CODEX_MODEL", "default").strip() or "default",
                "credential_mode": self._auth_ready(manifest)[1],
            })
        return payload

    @staticmethod
    def _credential_reference(raw_path: str) -> Mapping[str, Any] | None:
        if not raw_path:
            return None
        path = Path(raw_path).expanduser()
        if not path.exists():
            return None
        stat = path.stat()
        return {
            "path": str(path.resolve()),
            "kind": "directory" if path.is_dir() else "file",
            "size": stat.st_size if path.is_file() else None,
            "mtime_ns": stat.st_mtime_ns,
        }

    def _configuration_hash(self, manifest: RuntimeDriverManifest) -> str:
        return stable_configuration_hash(self._configuration_payload(manifest))

    def status(self) -> tuple[RuntimeDriverStatus, ...]:
        values: list[RuntimeDriverStatus] = []
        current_platform = platform.system().lower()
        for manifest in self.manifests:
            metadata: dict[str, Any] = {}
            executable = self._executable(manifest)
            version: str | None = None
            if current_platform not in manifest.supported_platforms:
                status = RuntimeDriverStatus(manifest, RuntimeDriverAvailability.UNAVAILABLE, reason="unsupported platform")
            elif manifest.implementation == RuntimeDriverImplementation.PLANNED:
                status = RuntimeDriverStatus(manifest, RuntimeDriverAvailability.DISABLED, executable=executable, reason="driver translator not implemented")
            elif not executable:
                status = RuntimeDriverStatus(manifest, RuntimeDriverAvailability.UNAVAILABLE, reason="CLI executable not found")
            else:
                version, version_error = self._probe_version(manifest, executable)
                auth_ready, auth_mode = self._auth_ready(manifest)
                metadata["auth_mode"] = auth_mode
                if version_error:
                    availability = RuntimeDriverAvailability.DEGRADED
                    reason = version_error
                else:
                    availability = RuntimeDriverAvailability.AVAILABLE if auth_ready else RuntimeDriverAvailability.DEGRADED
                    reason = None if auth_ready else "CLI found but authentication not detected"
                try:
                    exe_hash = executable_sha256(executable)
                except Exception as exc:
                    exe_hash = None
                    availability = RuntimeDriverAvailability.DEGRADED
                    reason = f"executable fingerprint failed: {type(exc).__name__}: {exc}"
                state, receipt, conformance_reason = self.conformance_store.validate(
                    manifest,
                    executable_path=str(Path(executable).resolve()),
                    executable_sha256=exe_hash,
                    runtime_version=version,
                    configuration_hash=self._configuration_hash(manifest),
                )
                reliability = reliability_snapshot(self.telemetry.path, manifest.driver_id, manifest.adapter_id)
                metadata.update({
                    "executable_sha256": exe_hash,
                    "conformance_state": state.value,
                    "conformance_reason": conformance_reason,
                    "conformance_receipt_id": receipt.receipt_id if receipt else None,
                    "conformance_receipt_fingerprint": receipt.fingerprint() if receipt else None,
                    "reliability": asdict(reliability),
                    "configuration_hash": self._configuration_hash(manifest),
                })
                status = RuntimeDriverStatus(
                    manifest, availability, executable=executable, runtime_version=version,
                    auth_ready=auth_ready, reason=reason, metadata=metadata,
                )
            values.append(status)
            self._emit(status)
        return tuple(values)

    def _enabled(self, driver_id: str) -> bool:
        env_name = {
            "openai-codex-cli": "AETHER_CODEX_DRIVER_ENABLED",
            "opencode-cli": "AETHER_OPENCODE_DRIVER_ENABLED",
            "google-gemini-cli": "AETHER_GEMINI_DRIVER_ENABLED",
            "anthropic-claude-code": "AETHER_CLAUDE_DRIVER_ENABLED",
        }.get(driver_id)
        if env_name:
            value = os.environ.get(env_name, "auto").strip().lower()
            if value in {"0", "false", "no", "disabled"}:
                return False
        return bool(self._raw_by_id[driver_id].get("enabled_by_default", False))

    def _raw_adapter(self, status: RuntimeDriverStatus) -> ExternalStreamingCodingRuntimeAdapter:
        manifest = status.manifest
        raw = self._raw_by_id[manifest.driver_id]
        runtime_env: dict[str, str] = {}
        if manifest.driver_id == "openai-codex-cli":
            if status.executable:
                runtime_env["AETHER_CODEX_BIN"] = status.executable
            for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_ORGANIZATION", "OPENAI_PROJECT", "CODEX_HOME", "AETHER_CODEX_HOME", "AETHER_CODEX_MODEL"):
                value = os.environ.get(key, "")
                if value:
                    runtime_env[key] = value
        elif manifest.driver_id == "opencode-cli":
            if status.executable:
                runtime_env["AETHER_OPENCODE_BIN"] = status.executable
            for key in ("AETHER_OPENCODE_API_KEY_FILE", "AETHER_OPENCODE_AUTH_FILE", "AETHER_OPENCODE_MODEL"):
                value = os.environ.get(key, "")
                if value:
                    runtime_env[key] = value
            runtime_env.setdefault("AETHER_OPENCODE_MODEL", str(raw.get("default_model") or "opencode/north-mini-code-free"))
        elif manifest.driver_id == "google-gemini-cli":
            if status.executable:
                runtime_env["AETHER_GEMINI_BIN"] = status.executable
            for key in ("AETHER_GEMINI_API_KEY_FILE", "AETHER_GEMINI_CREDENTIALS_FILE", "AETHER_GEMINI_MODEL"):
                value = os.environ.get(key, "")
                if value:
                    runtime_env[key] = value
            runtime_env.setdefault("AETHER_GEMINI_MODEL", str(raw.get("default_model") or "gemini-2.5-flash"))
        elif manifest.driver_id == "anthropic-claude-code":
            if status.executable:
                runtime_env["AETHER_CLAUDE_BIN"] = status.executable
            for key in ("AETHER_CLAUDE_API_KEY_FILE", "AETHER_CLAUDE_CONFIG_DIR", "CLAUDE_CONFIG_DIR", "AETHER_CLAUDE_MODEL"):
                value = os.environ.get(key, "")
                if value:
                    runtime_env[key] = value
            runtime_env.setdefault("AETHER_CLAUDE_MODEL", str(raw.get("default_model") or "sonnet"))
        else:
            raise RuntimeConformanceError(f"no translator builder for {manifest.driver_id}")
        module = str(raw["translator_module"])
        return ExternalStreamingCodingRuntimeAdapter(
            (sys.executable, "-m", module),
            self.state_root / manifest.driver_id,
            self.telemetry,
            allowed_workspace_roots=self.allowed_workspace_roots,
            event_bus=self.event_bus,
            routing_key=manifest.routing_key,
            adapter_id=manifest.adapter_id,
            display_name=manifest.display_name,
            priority=manifest.priority,
            runtime_env=runtime_env,
            environment_policy_id=str(raw.get("environment_policy_id") or "aether.runtime-driver.explicit-v1"),
        )

    def build_live_adapters(self) -> tuple[ConformanceGatedRuntimeAdapter, ...]:
        adapters: list[ConformanceGatedRuntimeAdapter] = []
        for status in self.status():
            manifest = status.manifest
            if manifest.implementation != RuntimeDriverImplementation.LIVE or not self._enabled(manifest.driver_id):
                continue
            # Vendor translators are registered only when their CLI exists. Codex
            # keeps the earlier non-fatal unavailable-body behavior for compatibility.
            if manifest.driver_id in {"opencode-cli", "google-gemini-cli", "anthropic-claude-code"} and not status.executable:
                continue
            raw_adapter = self._raw_adapter(status)
            exe_hash = status.metadata.get("executable_sha256") if status.metadata else None
            reliability = reliability_snapshot(self.telemetry.path, manifest.driver_id, manifest.adapter_id)
            quota_state = self._quota_state(status)
            quota_penalties = self.policy.get("reliability", {}).get("quota_penalty", {})
            quota_penalty = int(quota_penalties.get(quota_state.value, 0))
            adapters.append(ConformanceGatedRuntimeAdapter(
                raw_adapter, manifest, self.conformance_store,
                executable_path=str(Path(status.executable).resolve()) if status.executable else None,
                executable_sha256=str(exe_hash) if exe_hash else None,
                runtime_version=status.runtime_version,
                configuration_hash=self._configuration_hash(manifest),
                reliability=reliability,
                quota_state=quota_state.value,
                quota_priority_penalty=quota_penalty,
                configuration_hash_getter=lambda manifest=manifest: self._configuration_hash(manifest),
            ))
        return tuple(adapters)

    async def conform(self, driver_id: str, *, principal: str, ttl_hours: int | None = None) -> RuntimeConformanceReceipt:
        manifest = self.manifest(driver_id)
        if manifest.implementation != RuntimeDriverImplementation.LIVE:
            raise RuntimeConformanceError("planned driver cannot receive a live conformance receipt")
        status = {item.manifest.driver_id: item for item in self.status()}[driver_id]
        if not status.executable or not status.runtime_version:
            raise RuntimeConformanceError(status.reason or "driver executable/version is unavailable")
        if not status.auth_ready:
            raise RuntimeConformanceError("driver authentication is not ready")
        exe_hash = executable_sha256(status.executable)
        raw_adapter = self._raw_adapter(status)
        health = dict(await raw_adapter.health())
        checks = (
            RuntimeConformanceCheck("executable-hash", len(exe_hash) == 64, "exact executable SHA-256 captured"),
            RuntimeConformanceCheck("version-probe", bool(status.runtime_version), status.runtime_version or "missing version"),
            RuntimeConformanceCheck("authentication-readiness", status.auth_ready, str(status.metadata.get("auth_mode") or "ready")),
            RuntimeConformanceCheck("protocol-handshake", bool(health.get("ok")), str(health.get("protocol") or health.get("error") or "missing")),
            RuntimeConformanceCheck("capability-discovery", "coding.patch-generation" in set(health.get("capabilities") or ()), "required capability advertised"),
            RuntimeConformanceCheck("no-shell-boundary", health.get("shell") is False, "adapter reports argv execution without shell"),
        )
        now = datetime.now(timezone.utc)
        hours = int(ttl_hours or self.policy.get("conformance", {}).get("receipt_ttl_hours", 24))
        suite_raw = json.dumps({
            "suite_id": self.policy.get("conformance", {}).get("suite_id"),
            "checks": [item.name for item in checks],
            "protocol": manifest.protocol,
        }, sort_keys=True, separators=(",", ":"))
        config = self._configuration_payload(manifest)
        receipt = RuntimeConformanceReceipt(
            driver_id=driver_id,
            manifest_fingerprint=manifest.fingerprint(),
            executable_path=str(Path(status.executable).resolve()),
            executable_sha256=exe_hash,
            runtime_version=status.runtime_version,
            protocol=manifest.protocol,
            provider_id=str(config.get("provider_id") or manifest.vendor.lower()),
            model_id=str(config.get("model_id") or "default"),
            configuration_hash=self._configuration_hash(manifest),
            suite_hash=hashlib.sha256(suite_raw.encode("utf-8")).hexdigest(),
            issued_at=now.isoformat(),
            expires_at=(now + timedelta(hours=max(1, min(hours, 168)))).isoformat(),
            checks=checks,
            issued_by=principal,
            metadata={
                "suite_id": self.policy.get("conformance", {}).get("suite_id"),
                "health": {key: value for key, value in health.items() if key not in {"credentials", "environment"}},
                "authority": "routing_eligibility_only",
            },
        )
        self.conformance_store.append(receipt)
        passed = receipt.passed
        self._emit_conformance(receipt, passed)
        if not passed:
            raise RuntimeConformanceError("driver failed one or more conformance checks")
        return receipt

    def _quota_state(self, status: RuntimeDriverStatus) -> RuntimeQuotaState:
        if status.availability in {RuntimeDriverAvailability.UNAVAILABLE, RuntimeDriverAvailability.DISABLED}:
            return RuntimeQuotaState.UNAVAILABLE
        if not status.auth_ready:
            return RuntimeQuotaState.AUTHENTICATION_FAILED
        recent = self.telemetry.list_invocations(adapter_id=status.manifest.adapter_id, limit=20)
        for item in recent:
            if item.get("ok"):
                return RuntimeQuotaState.HEALTHY
            payload = item.get("payload") or {}
            text = json.dumps(payload, sort_keys=True, default=str).lower()
            if any(token in text for token in ("quota exhausted", "quota_exhausted", "insufficient_quota", "resource_exhausted")):
                return RuntimeQuotaState.QUOTA_EXHAUSTED
            if any(token in text for token in ("rate limit", "rate_limit", "too many requests", "http 429", "status 429")):
                return RuntimeQuotaState.RATE_LIMITED
            if any(token in text for token in ("unauthorized", "authentication", "invalid api key", "http 401", "status 401")):
                return RuntimeQuotaState.AUTHENTICATION_FAILED
        return RuntimeQuotaState.HEALTHY if status.availability == RuntimeDriverAvailability.AVAILABLE else RuntimeQuotaState.UNKNOWN

    def operations_console(self) -> Mapping[str, Any]:
        statuses = self.status()
        renewal_minutes = int(self.policy.get("conformance", {}).get("renewal_window_minutes", 120))
        now = datetime.now(timezone.utc)
        drivers: list[Mapping[str, Any]] = []
        for status in statuses:
            manifest = status.manifest
            state_raw = str(status.metadata.get("conformance_state") or RuntimeConformanceState.MISSING.value)
            try:
                state = RuntimeConformanceState(state_raw)
            except ValueError:
                state = RuntimeConformanceState.MISSING
            receipt = self.conformance_store.latest(manifest.driver_id)
            renewal_due = False
            if receipt is not None:
                try:
                    expires = datetime.fromisoformat(receipt.expires_at.replace("Z", "+00:00"))
                    renewal_due = expires <= now + timedelta(minutes=max(1, renewal_minutes))
                except ValueError:
                    renewal_due = True
            reliability = reliability_snapshot(self.telemetry.path, manifest.driver_id, manifest.adapter_id)
            quota = self._quota_state(status)
            routing_eligible = (
                manifest.implementation == RuntimeDriverImplementation.LIVE
                and status.availability == RuntimeDriverAvailability.AVAILABLE
                and status.auth_ready
                and state == RuntimeConformanceState.PASSED
                and quota not in {RuntimeQuotaState.QUOTA_EXHAUSTED, RuntimeQuotaState.AUTHENTICATION_FAILED, RuntimeQuotaState.UNAVAILABLE}
            )
            snapshot = RuntimeOperationsDriverSnapshot(
                driver_id=manifest.driver_id,
                availability=status.availability,
                conformance_state=state,
                routing_eligible=routing_eligible,
                runtime_version=status.runtime_version,
                model_id=str(self._configuration_payload(manifest).get("model_id") or "default"),
                provider_id=str(self._configuration_payload(manifest).get("provider_id") or manifest.vendor.lower()),
                reliability=reliability,
                quota_state=quota,
                receipt_id=receipt.receipt_id if receipt else None,
                receipt_expires_at=receipt.expires_at if receipt else None,
                renewal_due=renewal_due,
                reason=status.reason or str(status.metadata.get("conformance_reason") or ""),
                metadata={
                    "display_name": manifest.display_name,
                    "adapter_id": manifest.adapter_id,
                    "priority": manifest.priority,
                    "auth_ready": status.auth_ready,
                    "auth_mode": status.metadata.get("auth_mode"),
                    "quota_priority_penalty": int(self.policy.get("reliability", {}).get("quota_penalty", {}).get(quota.value, 0)),
                },
            )
            rendered = asdict(snapshot)
            rendered["availability"] = snapshot.availability.value
            rendered["conformance_state"] = snapshot.conformance_state.value
            rendered["quota_state"] = snapshot.quota_state.value
            rendered["reliability"] = asdict(snapshot.reliability)
            drivers.append(rendered)
        drivers.sort(key=lambda item: (
            not bool(item["routing_eligible"]),
            int(item["reliability"]["effective_priority_penalty"]),
            int(item["metadata"]["priority"]),
            str(item["driver_id"]),
        ))
        return {
            "policy_id": self.policy.get("operations_console", {}).get("policy_id"),
            "generated_at": now.isoformat(),
            "routing_eligible_count": sum(1 for item in drivers if item["routing_eligible"]),
            "renewal_due_count": sum(1 for item in drivers if item["renewal_due"]),
            "drivers": drivers,
            "telemetry": self.telemetry.status(),
            "secret_values_exposed": False,
        }

    async def renew_due_receipts(self, *, principal: str, ttl_hours: int | None = None) -> tuple[RuntimeConformanceReceipt, ...]:
        renewed: list[RuntimeConformanceReceipt] = []
        console = self.operations_console()
        for item in console["drivers"]:
            if not item["renewal_due"]:
                continue
            if item["availability"] != RuntimeDriverAvailability.AVAILABLE.value or not item["metadata"]["auth_ready"]:
                continue
            try:
                renewed.append(await self.conform(str(item["driver_id"]), principal=principal, ttl_hours=ttl_hours))
            except RuntimeConformanceError:
                continue
        return tuple(renewed)

    def as_dict(self) -> Mapping[str, Any]:
        statuses = self.status()
        return {
            "policy_id": self.policy.get("policy_id"),
            "preferred_live_drivers": list(self.policy.get("execution", {}).get("preferred_live_drivers", ())),
            "operations_console": self.operations_console(),
            "conformance_required": bool(self.policy.get("conformance", {}).get("required_for_live_routing", True)),
            "drivers": [self._status_dict(item) for item in statuses],
            "conformance_receipts": [self._receipt_dict(item) for item in self.conformance_store.list(limit=100)],
        }

    def _status_dict(self, status: RuntimeDriverStatus) -> Mapping[str, Any]:
        manifest = status.manifest
        return {
            "manifest": {
                **asdict(manifest),
                "implementation": manifest.implementation.value,
                "manifest_fingerprint": manifest.fingerprint(),
            },
            "availability": status.availability.value,
            "executable": status.executable,
            "runtime_version": status.runtime_version,
            "auth_ready": status.auth_ready,
            "reason": status.reason,
            "metadata": dict(status.metadata),
        }

    @staticmethod
    def _receipt_dict(receipt: RuntimeConformanceReceipt) -> Mapping[str, Any]:
        return {
            **asdict(receipt),
            "checks": [asdict(item) for item in receipt.checks],
            "passed": receipt.passed,
            "receipt_fingerprint": receipt.fingerprint(),
        }

    def _emit(self, status: RuntimeDriverStatus) -> None:
        if self.event_bus is None:
            return
        event_type = EventType.RUNTIME_DRIVER_DISCOVERED if status.availability in {RuntimeDriverAvailability.AVAILABLE, RuntimeDriverAvailability.DEGRADED} else EventType.RUNTIME_DRIVER_UNAVAILABLE
        self.event_bus.emit(event_type, actor="aether.runtime-driver-pack", payload={
            "driver_id": status.manifest.driver_id,
            "manifest_fingerprint": status.manifest.fingerprint(),
            "availability": status.availability.value,
            "executable": Path(status.executable).name if status.executable else None,
            "auth_ready": status.auth_ready,
            "reason": status.reason,
            "conformance_state": status.metadata.get("conformance_state") if status.metadata else None,
        }, severity="info" if event_type == EventType.RUNTIME_DRIVER_DISCOVERED else "warning")

    def _emit_conformance(self, receipt: RuntimeConformanceReceipt, passed: bool) -> None:
        if self.event_bus is None:
            return
        self.event_bus.emit(
            EventType.RUNTIME_DRIVER_CONFORMANCE_PASSED if passed else EventType.RUNTIME_DRIVER_CONFORMANCE_FAILED,
            actor="aether.runtime-driver-pack",
            payload={
                "driver_id": receipt.driver_id,
                "receipt_id": receipt.receipt_id,
                "receipt_fingerprint": receipt.fingerprint(),
                "manifest_fingerprint": receipt.manifest_fingerprint,
                "runtime_version": receipt.runtime_version,
                "provider_id": receipt.provider_id,
                "model_id": receipt.model_id,
                "expires_at": receipt.expires_at,
                "checks": [{"name": item.name, "ok": item.ok} for item in receipt.checks],
            },
            severity="info" if passed else "error",
        )
