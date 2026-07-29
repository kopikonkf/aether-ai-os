"""OpenCode CLI translator for Aether JSONL Streaming Protocol v1.

The translator invokes ``opencode run --format json`` inside a disposable copy,
normalizes vendor events, and emits complete-text patches. Production mutation
and verification remain owned by the parent Aether adapter.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

from aether.contracts import AETHER_CODING_STREAM_PROTOCOL

DRIVER_ID = "opencode-cli"
RUNTIME_ID = "opencode.cli"
DEFAULT_MODEL = "opencode/north-mini-code-free"
DEFAULT_MAX_EVENTS = 2000
DEFAULT_MAX_OUTPUT_BYTES = 4_194_304
DEFAULT_MAX_FILES = 20
DEFAULT_MAX_TOTAL_BYTES = 524_288
IGNORED_PARTS = {".git", ".opencode", ".agents", "__pycache__", ".pytest_cache", ".mypy_cache", "node_modules"}


class OpenCodeDriverError(RuntimeError):
    pass


class FrameWriter:
    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        self.sequence = 0

    def emit(self, frame_type: str, payload: Mapping[str, Any] | None = None) -> None:
        frame = {
            "type": frame_type,
            "protocol": AETHER_CODING_STREAM_PROTOCOL,
            "task_id": self.task_id,
            "sequence": self.sequence,
            "payload": dict(payload or {}),
        }
        self.sequence += 1
        sys.stdout.write(json.dumps(frame, sort_keys=True, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def _binary() -> str | None:
    configured = os.environ.get("AETHER_OPENCODE_BIN", "").strip()
    if configured:
        resolved = shutil.which(configured) if not Path(configured).is_absolute() else configured
        return str(resolved) if resolved and Path(resolved).exists() else None
    return shutil.which("opencode")


def _key_file() -> Path | None:
    raw = os.environ.get("AETHER_OPENCODE_API_KEY_FILE", "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser().resolve()
    return path if path.is_file() else None


def _model() -> str:
    return os.environ.get("AETHER_OPENCODE_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def _auth_ready() -> tuple[bool, str]:
    if os.environ.get("AETHER_OPENCODE_DRIVER_ALLOW_UNAUTHENTICATED", "").strip() == "1":
        return True, "test-override"
    key_file = _key_file()
    if key_file and key_file.stat().st_size > 0:
        return True, "api-key-file"
    auth_path = os.environ.get("AETHER_OPENCODE_AUTH_FILE", "").strip()
    if auth_path and Path(auth_path).expanduser().is_file():
        return True, "auth-file"
    return False, "missing-auth"


def _base_env() -> dict[str, str]:
    allowed = {
        "PATH", "SYSTEMROOT", "WINDIR", "TMP", "TEMP", "LANG", "LC_ALL",
        "SSL_CERT_FILE", "SSL_CERT_DIR", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
    }
    return {key: value for key, value in os.environ.items() if key in allowed and value}


def _config_content(key_file: Path, model: str) -> str:
    payload = {
        "$schema": "https://opencode.ai/config.json",
        "model": model,
        "small_model": model,
        "autoupdate": False,
        "share": "disabled",
        "provider": {"opencode": {"options": {"apiKey": "{file:" + str(key_file) + "}"}}},
        "permission": {
            "edit": "allow",
            "bash": "deny",
            "webfetch": "deny",
            "websearch": "deny",
            "external_directory": "deny",
        },
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _vendor_env(*, isolated_home: str, key_file: Path, model: str) -> dict[str, str]:
    env = _base_env()
    env.update({
        "HOME": isolated_home,
        "USERPROFILE": isolated_home,
        "XDG_CONFIG_HOME": str(Path(isolated_home) / ".config"),
        "XDG_DATA_HOME": str(Path(isolated_home) / ".local" / "share"),
        "XDG_CACHE_HOME": str(Path(isolated_home) / ".cache"),
        "OPENCODE_CONFIG_CONTENT": _config_content(key_file, model),
        "CI": "1",
        "NO_COLOR": "1",
    })
    return env


async def _version(binary: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        binary, "--version", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env=_base_env(),
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
    except asyncio.TimeoutError as exc:
        proc.kill(); await proc.communicate()
        raise OpenCodeDriverError("OpenCode CLI version discovery timed out") from exc
    if proc.returncode != 0:
        raise OpenCodeDriverError(f"OpenCode CLI version discovery failed: {stderr.decode(errors='replace')[-1000:]}")
    value = (stdout or stderr).decode("utf-8", errors="replace").strip()
    if not value:
        raise OpenCodeDriverError("OpenCode CLI returned an empty version")
    return value[:200]


def _handshake_payload(version: str, auth_ready: bool, auth_mode: str) -> dict[str, Any]:
    return {
        "protocol": AETHER_CODING_STREAM_PROTOCOL,
        "runtime": {
            "id": RUNTIME_ID,
            "version": version,
            "display_name": "OpenCode CLI Driver",
            "operations": ["coding.task.execute"],
            "capabilities": ["coding.edit", "coding.verify", "coding.patch-generation", "coding.artifact-return"],
            "features": [
                "external-cli", "jsonl-stream-v1", "vendor-driver-pack-v1", "vendor-driver-pack-v2", "opencode-run-json",
                "provider-agnostic", "generative-coding", "runtime-generated-patch",
                "independent-verification", "workspace-binding", "progress-events",
                "bounded-artifacts", "verification-receipts", "no-shell",
            ],
            "metadata": {
                "driver_id": DRIVER_ID,
                "vendor": "OpenCode",
                "vendor_event_protocol": "opencode.run-json",
                "auth_ready": auth_ready,
                "auth_mode": auth_mode,
                "model_id": _model(),
                "degraded": not auth_ready,
                "authority": "body_only",
                "credential_transport": "file-reference",
            },
        },
        "limits": {"max_frame_bytes": 1_048_576, "max_patch_files": DEFAULT_MAX_FILES},
    }


async def handshake() -> int:
    binary = _binary()
    if not binary:
        sys.stderr.write("OpenCode CLI executable was not found\n")
        return 3
    try:
        version = await _version(binary)
    except Exception as exc:
        sys.stderr.write(f"{type(exc).__name__}: {exc}\n")
        return 4
    auth_ready, auth_mode = _auth_ready()
    sys.stdout.write(json.dumps(_handshake_payload(version, auth_ready, auth_mode), sort_keys=True) + "\n")
    return 0


def _snapshot(root: Path, allowed: tuple[str, ...], max_files: int, max_bytes: int) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    total = 0
    roots: list[Path] = []
    for raw in allowed or (".",):
        rel = Path(raw)
        if rel.is_absolute() or ".." in rel.parts:
            raise OpenCodeDriverError(f"invalid allowed path: {raw}")
        candidate = (root / rel).resolve()
        if candidate != root and root not in candidate.parents:
            raise OpenCodeDriverError(f"allowed path escapes workspace: {raw}")
        roots.append(candidate)
    seen: set[Path] = set()
    for start in roots:
        if not start.exists():
            continue
        iterator = [start] if start.is_file() else start.rglob("*")
        for path in iterator:
            if not path.is_file() or path in seen or any(part in IGNORED_PARTS for part in path.relative_to(root).parts):
                continue
            seen.add(path)
            rel = path.relative_to(root).as_posix()
            data = path.read_bytes()
            if b"\x00" in data:
                continue
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                continue
            total += len(data)
            if len(result) >= max_files or total > max_bytes:
                raise OpenCodeDriverError("workspace snapshot exceeds driver limits")
            result[rel] = (hashlib.sha256(data).hexdigest(), text)
    return result


def _prompt(request: Mapping[str, Any]) -> str:
    task = dict(request.get("task") or {})
    objective = str(task.get("objective") or "").strip()
    if not objective:
        raise OpenCodeDriverError("coding objective is required")
    allowed = list(dict(request.get("workspace") or {}).get("allowed_relative_paths") or ["."])
    return (
        "You are a replaceable coding body for Aether OS. Work only in the current disposable workspace. "
        "Do not access parent paths, credentials, network tools, .git, .opencode, or .agents. "
        "Make the smallest correct source change. Aether independently verifies every file and may reject it.\n"
        f"Allowed relative paths: {json.dumps(allowed)}\nObjective: {objective}\n"
        "Finish after editing the workspace; do not merely describe the patch."
    )


def _argv(binary: str, vendor_root: Path, prompt: str, model: str) -> list[str]:
    return [
        binary, "run", "--format", "json", "--model", model,
        "--dir", str(vendor_root), "--auto", prompt,
    ]


def _event_summary(event: Mapping[str, Any]) -> tuple[str, str, float | None, dict[str, Any], bool]:
    event_type = str(event.get("type") or event.get("event") or "unknown")
    part = event.get("part") if isinstance(event.get("part"), Mapping) else {}
    part_type = str(part.get("type") or event.get("part_type") or "")
    payload: dict[str, Any] = {"vendor_event_type": event_type}
    if part_type:
        payload["part_type"] = part_type
    lowered = event_type.lower()
    fatal = lowered in {"error", "failed", "session.error", "turn.failed"}
    if fatal:
        payload["error"] = str(event.get("error") or event.get("message") or part.get("text") or "OpenCode failed")[:2000]
        return "opencode-failed", "OpenCode reported a terminal failure.", None, payload, True
    if lowered in {"session.created", "session_start", "session.started", "start"}:
        return "opencode-session", "OpenCode session started.", 10.0, payload, False
    if "tool" in lowered or part_type in {"tool", "tool-use", "tool_result", "tool-result"}:
        tool_name = part.get("tool") or part.get("name") or event.get("tool") or "tool"
        payload["tool"] = str(tool_name)[:200]
        return "opencode-tool", "OpenCode emitted a tool event.", 50.0, payload, False
    if "text" in lowered or part_type == "text":
        text = part.get("text") or event.get("text") or event.get("message") or ""
        payload["text"] = str(text)[:2000]
        return "opencode-message", "OpenCode emitted a text event.", 65.0, payload, False
    if lowered in {"result", "done", "complete", "completed", "session.completed", "step_finish"}:
        return "opencode-completed", "OpenCode stream completed.", 82.0, payload, False
    return "opencode-event", f"OpenCode event: {event_type}", None, payload, False


def _read_secret_for_redaction(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _redact(value: str, secret: str) -> str:
    return value.replace(secret, "[REDACTED]") if secret else value


async def run_task() -> int:
    line = sys.stdin.readline()
    try:
        request = json.loads(line)
    except Exception as exc:
        sys.stderr.write(f"invalid Aether task request: {exc}\n")
        return 2
    task = dict(request.get("task") or {})
    task_id = str(task.get("task_id") or "")
    writer = FrameWriter(task_id)
    try:
        if str(request.get("type") or "") != "task.start" or str(request.get("protocol") or "") != AETHER_CODING_STREAM_PROTOCOL:
            raise OpenCodeDriverError("unsupported Aether task request")
        binary = _binary()
        if not binary:
            raise OpenCodeDriverError("OpenCode CLI executable was not found")
        auth_ready, auth_mode = _auth_ready()
        key_file = _key_file()
        if not auth_ready or key_file is None:
            raise OpenCodeDriverError("OpenCode Zen API key file is not configured")
        workspace = Path(str(dict(request.get("workspace") or {}).get("root") or "")).resolve()
        if not workspace.is_dir():
            raise OpenCodeDriverError("staging workspace does not exist")
        limits = dict(request.get("limits") or {})
        max_files = min(DEFAULT_MAX_FILES, max(1, int(limits.get("maximum_files") or DEFAULT_MAX_FILES)))
        max_bytes = min(DEFAULT_MAX_TOTAL_BYTES, max(1, int(limits.get("maximum_total_bytes") or DEFAULT_MAX_TOTAL_BYTES)))
        max_frame_bytes = max(4096, int(limits.get("maximum_frame_bytes") or 65536))
        allowed = tuple(str(item) for item in dict(request.get("workspace") or {}).get("allowed_relative_paths") or (".",))
        before = _snapshot(workspace, allowed, max_files=max(500, max_files * 20), max_bytes=52_428_800)
        model = _model()
        writer.emit("task.accepted", {
            "phase": "driver", "message": "OpenCode CLI driver accepted the staging task.", "percent": 2.0,
            "driver_id": DRIVER_ID, "auth_mode": auth_mode, "model_id": model,
        })
        prompt = _prompt(request)
        max_events = max(1, int(os.environ.get("AETHER_OPENCODE_MAX_EVENTS", DEFAULT_MAX_EVENTS)))
        max_output = max(1024, int(os.environ.get("AETHER_OPENCODE_MAX_OUTPUT_BYTES", DEFAULT_MAX_OUTPUT_BYTES)))
        secret = _read_secret_for_redaction(key_file)
        with tempfile.TemporaryDirectory(prefix="aether-opencode-run-") as vendor_root_raw, tempfile.TemporaryDirectory(prefix="aether-opencode-home-") as isolated_home:
            vendor_root = Path(vendor_root_raw) / "workspace"
            shutil.copytree(workspace, vendor_root, ignore=shutil.ignore_patterns(".git", ".opencode", ".agents", "__pycache__", ".pytest_cache"))
            proc = await asyncio.create_subprocess_exec(
                *_argv(binary, vendor_root, prompt, model), cwd=str(vendor_root),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env=_vendor_env(isolated_home=isolated_home, key_file=key_file, model=model), limit=1_048_576,
            )
            assert proc.stdout is not None and proc.stderr is not None
            stderr_task = asyncio.create_task(proc.stderr.read(max_output + 1))
            events = 0; output_bytes = 0; fatal: str | None = None
            normalized = 0; suppressed = 0
            max_normalized = max(20, int(os.environ.get("AETHER_OPENCODE_MAX_NORMALIZED_FRAMES", "400")))
            while True:
                raw = await proc.stdout.readline()
                if not raw:
                    break
                events += 1; output_bytes += len(raw)
                if events > max_events or output_bytes > max_output:
                    proc.kill(); raise OpenCodeDriverError("OpenCode JSON stream exceeds driver limits")
                try:
                    event = json.loads(raw.decode("utf-8", errors="strict"))
                except Exception as exc:
                    proc.kill(); raise OpenCodeDriverError("OpenCode emitted malformed JSON") from exc
                phase, message, percent, metadata, event_fatal = _event_summary(event)
                metadata = json.loads(_redact(json.dumps(metadata, default=str), secret))
                if event_fatal:
                    fatal = str(metadata.get("error") or message)
                if normalized < max_normalized or event_fatal:
                    writer.emit("task.progress", {"phase": phase, "message": message, "percent": percent, "metadata": metadata})
                    normalized += 1
                else:
                    suppressed += 1
            exit_code = await proc.wait()
            stderr = await stderr_task
            if len(stderr) > max_output:
                raise OpenCodeDriverError("OpenCode stderr exceeds driver limits")
            stderr_text = _redact(stderr.decode(errors="replace"), secret)
            if exit_code != 0:
                raise OpenCodeDriverError(f"OpenCode CLI exited with code {exit_code}: {stderr_text[-2000:]}")
            if fatal:
                raise OpenCodeDriverError(fatal)
            if suppressed:
                writer.emit("task.progress", {
                    "phase": "opencode-stream-summary",
                    "message": f"Suppressed {suppressed} low-priority vendor events after normalization limit.",
                    "percent": 84.0, "metadata": {"suppressed_vendor_events": suppressed},
                })
            after = _snapshot(vendor_root, allowed, max_files=max(500, max_files * 20), max_bytes=52_428_800)
        changed = sorted(set(before) | set(after))
        patches: list[tuple[str, str, str | None]] = []
        total = 0
        for path in changed:
            old = before.get(path); new = after.get(path)
            if old == new:
                continue
            if new is None:
                raise OpenCodeDriverError(f"OpenCode deleted {path}; deletion is not supported by protocol v1")
            content = new[1]; content_bytes = len(content.encode("utf-8")); total += content_bytes
            if content_bytes > max_frame_bytes - 4096:
                raise OpenCodeDriverError(f"generated file exceeds protocol v1 frame limit: {path}")
            if len(patches) >= max_files or total > max_bytes:
                raise OpenCodeDriverError("OpenCode generated patch exceeds task limits")
            patches.append((path, content, old[0] if old else None))
        if not patches:
            raise OpenCodeDriverError("OpenCode completed without producing a workspace patch")
        for path, content, before_hash in patches:
            writer.emit("artifact.patch", {
                "path": path, "content": content, "before_sha256": before_hash, "kind": "upsert",
                "metadata": {"driver_id": DRIVER_ID, "vendor": "OpenCode", "model_id": model, "authoritative_diff": False},
            })
        writer.emit("task.completed", {
            "ok": True, "phase": "driver-completed", "message": "OpenCode patch translated for Aether verification.",
            "patch_files": len(patches), "driver_id": DRIVER_ID, "model_id": model,
        })
        return 0
    except Exception as exc:
        writer.emit("task.error", {"error": f"{type(exc).__name__}: {exc}", "driver_id": DRIVER_ID})
        return 1


async def _main() -> int:
    if "--aether-handshake" in sys.argv:
        return await handshake()
    if "--aether-run" in sys.argv:
        return await run_task()
    sys.stderr.write("Usage: python -m aether_gateway.runtime_drivers.opencode_cli --aether-handshake|--aether-run\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
