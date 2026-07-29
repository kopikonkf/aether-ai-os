"""Claude Code translator for Aether JSONL Streaming Protocol v1.

Claude Code runs in print mode inside a disposable workspace. Only bounded file
read/edit tools are pre-authorized; shell, network, MCP, notebook, and agent
delegation surfaces are denied. Aether independently verifies all generated
bytes before production mutation.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

from aether.contracts import AETHER_CODING_STREAM_PROTOCOL

from .driver_common import (
    DriverBoundaryError,
    FrameWriter,
    coding_prompt,
    emit_patches,
    read_secret,
    redact_mapping,
    redact_text,
    snapshot,
)

DRIVER_ID = "anthropic-claude-code"
RUNTIME_ID = "claude.code"
DEFAULT_MODEL = "sonnet"
DEFAULT_MAX_EVENTS = 2500
DEFAULT_MAX_OUTPUT_BYTES = 4_194_304
DEFAULT_MAX_FILES = 20
DEFAULT_MAX_TOTAL_BYTES = 524_288


class ClaudeCodeDriverError(RuntimeError):
    pass


def _binary() -> str | None:
    configured = os.environ.get("AETHER_CLAUDE_BIN", "").strip()
    if configured:
        resolved = shutil.which(configured) if not Path(configured).is_absolute() else configured
        return str(resolved) if resolved and Path(resolved).is_file() else None
    return shutil.which("claude")


def _key_file() -> Path | None:
    raw = os.environ.get("AETHER_CLAUDE_API_KEY_FILE", "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser().resolve()
    return path if path.is_file() and path.stat().st_size > 0 else None


def _config_dir() -> Path | None:
    raw = os.environ.get("AETHER_CLAUDE_CONFIG_DIR", "").strip() or os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    if raw:
        path = Path(raw).expanduser().resolve()
        return path if path.is_dir() else None
    default = Path.home() / ".claude"
    return default.resolve() if default.is_dir() else None


def _model() -> str:
    return os.environ.get("AETHER_CLAUDE_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def _auth_ready() -> tuple[bool, str]:
    if os.environ.get("AETHER_CLAUDE_DRIVER_ALLOW_UNAUTHENTICATED", "").strip() == "1":
        return True, "test-override"
    if _key_file() is not None:
        return True, "api-key-file"
    config = _config_dir()
    if config is not None and any(path.is_file() for path in config.iterdir()):
        return True, "claude-config-dir"
    return False, "missing-auth"


def _base_env() -> dict[str, str]:
    allowed = {
        "PATH", "SYSTEMROOT", "WINDIR", "TMP", "TEMP", "LANG", "LC_ALL",
        "SSL_CERT_FILE", "SSL_CERT_DIR", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
    }
    return {key: value for key, value in os.environ.items() if key in allowed and value}


def _copy_auth_config(source: Path | None, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    if source is None:
        return
    ignored = {"projects", "history.jsonl", "session-env", "todos", "stats-cache.json", "debug"}
    for child in source.iterdir():
        if child.name in ignored:
            continue
        target = destination / child.name
        try:
            if child.is_dir():
                shutil.copytree(child, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns("*.log", "*.jsonl"))
            elif child.is_file() and child.stat().st_size <= 2_000_000:
                shutil.copy2(child, target)
        except OSError:
            continue


def _vendor_env(*, isolated_home: Path, key_file: Path | None, source_config: Path | None) -> dict[str, str]:
    isolated_config = isolated_home / ".claude"
    _copy_auth_config(source_config, isolated_config)
    env = _base_env()
    env.update({
        "HOME": str(isolated_home),
        "USERPROFILE": str(isolated_home),
        "CLAUDE_CONFIG_DIR": str(isolated_config),
        "DISABLE_AUTOUPDATER": "1",
        "DISABLE_TELEMETRY": "1",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "CI": "1",
        "NO_COLOR": "1",
    })
    if key_file is not None:
        env["ANTHROPIC_API_KEY"] = key_file.read_text(encoding="utf-8").strip()
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
        raise ClaudeCodeDriverError("Claude Code version discovery timed out") from exc
    if proc.returncode != 0:
        raise ClaudeCodeDriverError(f"Claude Code version discovery failed: {stderr.decode(errors='replace')[-1000:]}")
    value = (stdout or stderr).decode("utf-8", errors="replace").strip()
    if not value:
        raise ClaudeCodeDriverError("Claude Code returned an empty version")
    return value[:200]


def _handshake_payload(version: str, auth_ready: bool, auth_mode: str) -> dict[str, Any]:
    return {
        "protocol": AETHER_CODING_STREAM_PROTOCOL,
        "runtime": {
            "id": RUNTIME_ID,
            "version": version,
            "display_name": "Claude Code Driver",
            "operations": ["coding.task.execute"],
            "capabilities": ["coding.edit", "coding.verify", "coding.patch-generation", "coding.artifact-return"],
            "features": [
                "external-cli", "jsonl-stream-v1", "vendor-driver-pack-v3", "claude-stream-json",
                "generative-coding", "runtime-generated-patch", "independent-verification",
                "workspace-binding", "progress-events", "bounded-artifacts", "verification-receipts",
                "no-shell", "tool-allowlist", "quota-classification-v1",
            ],
            "metadata": {
                "driver_id": DRIVER_ID,
                "vendor": "Anthropic",
                "vendor_event_protocol": "claude-code.stream-json",
                "auth_ready": auth_ready,
                "auth_mode": auth_mode,
                "model_id": _model(),
                "degraded": not auth_ready,
                "authority": "body_only",
                "credential_transport": "file-reference-or-isolated-config-copy",
            },
        },
        "limits": {"max_frame_bytes": 1_048_576, "max_patch_files": DEFAULT_MAX_FILES},
    }


async def handshake() -> int:
    binary = _binary()
    if not binary:
        sys.stderr.write("Claude Code executable was not found\n")
        return 3
    try:
        version = await _version(binary)
    except Exception as exc:
        sys.stderr.write(f"{type(exc).__name__}: {exc}\n")
        return 4
    auth_ready, auth_mode = _auth_ready()
    sys.stdout.write(json.dumps(_handshake_payload(version, auth_ready, auth_mode), sort_keys=True) + "\n")
    return 0


def _argv(binary: str, prompt: str, model: str) -> list[str]:
    return [
        binary,
        "-p", prompt,
        "--output-format", "stream-json",
        "--verbose",
        "--max-turns", "8",
        "--model", model,
        "--allowedTools", "Read,Write,Edit,Glob,Grep",
        "--disallowedTools", "Bash,WebFetch,WebSearch,NotebookEdit,Task",
    ]


def _content_text(event: Mapping[str, Any]) -> str:
    message = event.get("message")
    if isinstance(message, Mapping):
        content = message.get("content")
    else:
        content = event.get("content")
    if isinstance(content, list):
        texts: list[str] = []
        for item in content:
            if isinstance(item, Mapping):
                text = item.get("text") or item.get("content")
                if text:
                    texts.append(str(text))
        return "\n".join(texts)
    return str(content or event.get("result") or "")


def _event_summary(event: Mapping[str, Any]) -> tuple[str, str, float | None, dict[str, Any], bool, bool]:
    event_type = str(event.get("type") or event.get("event") or "unknown")
    subtype = str(event.get("subtype") or "")
    payload: dict[str, Any] = {"vendor_event_type": event_type}
    if subtype:
        payload["subtype"] = subtype
    lowered = event_type.lower()
    if lowered == "system":
        payload["session_id"] = event.get("session_id")
        payload["model"] = event.get("model")
        return "claude-session", "Claude Code session initialized.", 10.0, payload, False, False
    if lowered == "assistant":
        payload["content"] = _content_text(event)[:2000]
        return "claude-message", "Claude Code emitted an assistant event.", 45.0, payload, False, False
    if lowered in {"user", "tool", "tool_use", "tool_result"}:
        payload["tool"] = event.get("tool_name") or event.get("name")
        return "claude-tool", "Claude Code emitted a tool event.", 62.0, payload, False, False
    if lowered in {"error", "failed"}:
        payload["error"] = str(event.get("error") or event.get("message") or "Claude Code failed")[:2000]
        return "claude-failed", "Claude Code reported a terminal failure.", None, payload, True, False
    if lowered == "result":
        payload["cost_usd"] = event.get("total_cost_usd")
        payload["duration_ms"] = event.get("duration_ms")
        payload["num_turns"] = event.get("num_turns")
        payload["usage"] = event.get("usage") or {}
        fatal = bool(event.get("is_error")) or subtype in {"error", "failed"}
        if fatal:
            payload["error"] = str(event.get("result") or event.get("error") or "Claude Code result failed")[:2000]
            return "claude-failed", "Claude Code result reported failure.", None, payload, True, True
        return "claude-completed", "Claude Code stream completed.", 82.0, payload, False, True
    if lowered == "stream_event":
        nested = event.get("event") if isinstance(event.get("event"), Mapping) else {}
        payload["nested_type"] = nested.get("type")
        return "claude-stream", "Claude Code emitted a partial stream event.", 35.0, payload, False, False
    return "claude-event", f"Claude Code event: {event_type}", None, payload, False, False


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
            raise ClaudeCodeDriverError("unsupported Aether task request")
        binary = _binary()
        if not binary:
            raise ClaudeCodeDriverError("Claude Code executable was not found")
        auth_ready, auth_mode = _auth_ready()
        key_file = _key_file()
        source_config = _config_dir()
        if not auth_ready:
            raise ClaudeCodeDriverError("Claude Code authentication is not configured")
        workspace = Path(str(dict(request.get("workspace") or {}).get("root") or "")).resolve()
        if not workspace.is_dir():
            raise ClaudeCodeDriverError("staging workspace does not exist")
        limits = dict(request.get("limits") or {})
        max_files = min(DEFAULT_MAX_FILES, max(1, int(limits.get("maximum_files") or DEFAULT_MAX_FILES)))
        max_bytes = min(DEFAULT_MAX_TOTAL_BYTES, max(1, int(limits.get("maximum_total_bytes") or DEFAULT_MAX_TOTAL_BYTES)))
        max_frame_bytes = max(4096, int(limits.get("maximum_frame_bytes") or 65536))
        allowed = tuple(str(item) for item in dict(request.get("workspace") or {}).get("allowed_relative_paths") or (".",))
        before = snapshot(workspace, allowed, max_files=max(500, max_files * 20), max_bytes=52_428_800)
        model = _model()
        writer.emit("task.accepted", {
            "phase": "driver", "message": "Claude Code driver accepted the staging task.", "percent": 2.0,
            "driver_id": DRIVER_ID, "auth_mode": auth_mode, "model_id": model,
        })
        prompt = coding_prompt(request, vendor="Claude Code", denied_surfaces="Do not use Bash, network, MCP, notebook, or subagent tools.")
        max_events = max(1, int(os.environ.get("AETHER_CLAUDE_MAX_EVENTS", DEFAULT_MAX_EVENTS)))
        max_output = max(1024, int(os.environ.get("AETHER_CLAUDE_MAX_OUTPUT_BYTES", DEFAULT_MAX_OUTPUT_BYTES)))
        secrets = [read_secret(key_file)]
        with tempfile.TemporaryDirectory(prefix="aether-claude-run-") as vendor_root_raw, tempfile.TemporaryDirectory(prefix="aether-claude-home-") as isolated_home_raw:
            vendor_root = Path(vendor_root_raw) / "workspace"
            isolated_home = Path(isolated_home_raw)
            shutil.copytree(workspace, vendor_root, ignore=shutil.ignore_patterns(".git", ".claude", ".agents", "__pycache__", ".pytest_cache"))
            proc = await asyncio.create_subprocess_exec(
                *_argv(binary, prompt, model), cwd=str(vendor_root),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env=_vendor_env(isolated_home=isolated_home, key_file=key_file, source_config=source_config),
                limit=1_048_576,
            )
            assert proc.stdout is not None and proc.stderr is not None
            stderr_task = asyncio.create_task(proc.stderr.read(max_output + 1))
            events = 0; output_bytes = 0; fatal: str | None = None; completed = False
            normalized = 0; suppressed = 0
            max_normalized = max(20, int(os.environ.get("AETHER_CLAUDE_MAX_NORMALIZED_FRAMES", "500")))
            while True:
                raw = await proc.stdout.readline()
                if not raw:
                    break
                events += 1; output_bytes += len(raw)
                if events > max_events or output_bytes > max_output:
                    proc.kill(); raise ClaudeCodeDriverError("Claude Code stream exceeds driver limits")
                try:
                    event = json.loads(raw.decode("utf-8", errors="strict"))
                except Exception as exc:
                    proc.kill(); raise ClaudeCodeDriverError("Claude Code emitted malformed JSONL") from exc
                phase, message, percent, metadata, event_fatal, event_completed = _event_summary(event)
                metadata = redact_mapping(metadata, secrets)
                completed = completed or event_completed
                if event_fatal:
                    fatal = str(metadata.get("error") or message)
                if normalized < max_normalized or event_fatal or event_completed:
                    writer.emit("task.progress", {"phase": phase, "message": message, "percent": percent, "metadata": metadata})
                    normalized += 1
                else:
                    suppressed += 1
            exit_code = await proc.wait()
            stderr = await stderr_task
            if len(stderr) > max_output:
                raise ClaudeCodeDriverError("Claude Code stderr exceeds driver limits")
            stderr_text = redact_text(stderr.decode(errors="replace"), secrets)
            if exit_code != 0:
                raise ClaudeCodeDriverError(f"Claude Code exited with code {exit_code}: {stderr_text[-2000:]}")
            if fatal:
                raise ClaudeCodeDriverError(fatal)
            if not completed:
                raise ClaudeCodeDriverError("Claude Code stream ended without a result event")
            if suppressed:
                writer.emit("task.progress", {
                    "phase": "claude-stream-summary",
                    "message": f"Suppressed {suppressed} low-priority vendor events after normalization limit.",
                    "percent": 84.0, "metadata": {"suppressed_vendor_events": suppressed},
                })
            after = snapshot(vendor_root, allowed, max_files=max(500, max_files * 20), max_bytes=52_428_800)
        patch_files = emit_patches(
            writer, before=before, after=after, max_files=max_files, max_bytes=max_bytes,
            max_frame_bytes=max_frame_bytes, driver_id=DRIVER_ID, vendor="Anthropic Claude Code", model_id=model,
        )
        writer.emit("task.completed", {
            "ok": True, "phase": "driver-completed", "message": "Claude Code patch translated for Aether verification.",
            "patch_files": patch_files, "driver_id": DRIVER_ID, "model_id": model,
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
    sys.stderr.write("Usage: python -m aether_gateway.runtime_drivers.claude_code --aether-handshake|--aether-run\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
