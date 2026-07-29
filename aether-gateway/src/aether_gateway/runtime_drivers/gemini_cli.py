"""Gemini CLI translator for Aether JSONL Streaming Protocol v1.

The vendor process runs in a disposable workspace with a supplemental user
policy that denies shell/network tools. Its stream is normalized and its file
changes are emitted as untrusted complete-text patches for Aether verification.
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

DRIVER_ID = "google-gemini-cli"
RUNTIME_ID = "gemini.cli"
DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_MAX_EVENTS = 2000
DEFAULT_MAX_OUTPUT_BYTES = 4_194_304
DEFAULT_MAX_FILES = 20
DEFAULT_MAX_TOTAL_BYTES = 524_288


class GeminiDriverError(RuntimeError):
    pass


def _binary() -> str | None:
    configured = os.environ.get("AETHER_GEMINI_BIN", "").strip()
    if configured:
        resolved = shutil.which(configured) if not Path(configured).is_absolute() else configured
        return str(resolved) if resolved and Path(resolved).is_file() else None
    return shutil.which("gemini")


def _key_file() -> Path | None:
    raw = os.environ.get("AETHER_GEMINI_API_KEY_FILE", "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser().resolve()
    return path if path.is_file() and path.stat().st_size > 0 else None


def _credentials_file() -> Path | None:
    raw = os.environ.get("AETHER_GEMINI_CREDENTIALS_FILE", "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser().resolve()
    return path if path.is_file() else None


def _model() -> str:
    return os.environ.get("AETHER_GEMINI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def _auth_ready() -> tuple[bool, str]:
    if os.environ.get("AETHER_GEMINI_DRIVER_ALLOW_UNAUTHENTICATED", "").strip() == "1":
        return True, "test-override"
    if _key_file() is not None:
        return True, "api-key-file"
    if _credentials_file() is not None:
        return True, "application-credentials-file"
    return False, "missing-auth"


def _base_env() -> dict[str, str]:
    allowed = {
        "PATH", "SYSTEMROOT", "WINDIR", "TMP", "TEMP", "LANG", "LC_ALL",
        "SSL_CERT_FILE", "SSL_CERT_DIR", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
    }
    return {key: value for key, value in os.environ.items() if key in allowed and value}


def _prepare_gemini_home(isolated_home: Path) -> None:
    gemini_dir = isolated_home / ".gemini"
    policies = gemini_dir / "policies"
    policies.mkdir(parents=True, exist_ok=True)
    (gemini_dir / "settings.json").write_text(json.dumps({
        "security": {"disableYoloMode": True},
        "telemetry": {"enabled": False},
        "tools": {
            "core": ["read_file", "write_file", "replace", "glob", "grep_search", "list_directory"],
        },
    }, sort_keys=True), encoding="utf-8")
    (policies / "aether-runtime.toml").write_text(
        '[[rule]]\n'
        'toolName = "run_shell_command"\n'
        'decision = "deny"\n'
        'priority = 999\n'
        'interactive = false\n'
        'denyMessage = "Aether runtime policy denies shell execution; verification is external."\n\n'
        '[[rule]]\n'
        'toolName = ["web_fetch", "google_web_search", "web_search"]\n'
        'decision = "deny"\n'
        'priority = 999\n'
        'interactive = false\n\n'
        '[[rule]]\n'
        'toolName = ["write_file", "replace"]\n'
        'decision = "allow"\n'
        'priority = 900\n'
        'interactive = false\n',
        encoding="utf-8",
    )


def _vendor_env(*, isolated_home: Path, key_file: Path | None, credentials_file: Path | None) -> dict[str, str]:
    _prepare_gemini_home(isolated_home)
    env = _base_env()
    env.update({
        "HOME": str(isolated_home),
        "USERPROFILE": str(isolated_home),
        "XDG_CONFIG_HOME": str(isolated_home / ".config"),
        "XDG_DATA_HOME": str(isolated_home / ".local" / "share"),
        "XDG_CACHE_HOME": str(isolated_home / ".cache"),
        "CI": "1",
        "NO_COLOR": "1",
        "GEMINI_CLI_NO_RELAUNCH": "1",
    })
    if key_file is not None:
        env["GEMINI_API_KEY"] = key_file.read_text(encoding="utf-8").strip()
    if credentials_file is not None:
        env["GOOGLE_APPLICATION_CREDENTIALS"] = str(credentials_file)
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
        raise GeminiDriverError("Gemini CLI version discovery timed out") from exc
    if proc.returncode != 0:
        raise GeminiDriverError(f"Gemini CLI version discovery failed: {stderr.decode(errors='replace')[-1000:]}")
    value = (stdout or stderr).decode("utf-8", errors="replace").strip()
    if not value:
        raise GeminiDriverError("Gemini CLI returned an empty version")
    return value[:200]


def _handshake_payload(version: str, auth_ready: bool, auth_mode: str) -> dict[str, Any]:
    return {
        "protocol": AETHER_CODING_STREAM_PROTOCOL,
        "runtime": {
            "id": RUNTIME_ID,
            "version": version,
            "display_name": "Gemini CLI Driver",
            "operations": ["coding.task.execute"],
            "capabilities": ["coding.edit", "coding.verify", "coding.patch-generation", "coding.artifact-return"],
            "features": [
                "external-cli", "jsonl-stream-v1", "vendor-driver-pack-v3", "gemini-stream-json",
                "generative-coding", "runtime-generated-patch", "independent-verification",
                "workspace-binding", "progress-events", "bounded-artifacts", "verification-receipts",
                "no-shell", "supplemental-policy", "quota-classification-v1",
            ],
            "metadata": {
                "driver_id": DRIVER_ID,
                "vendor": "Google",
                "vendor_event_protocol": "gemini.stream-json",
                "auth_ready": auth_ready,
                "auth_mode": auth_mode,
                "model_id": _model(),
                "degraded": not auth_ready,
                "authority": "body_only",
                "credential_transport": "file-reference-to-process-environment",
            },
        },
        "limits": {"max_frame_bytes": 1_048_576, "max_patch_files": DEFAULT_MAX_FILES},
    }


async def handshake() -> int:
    binary = _binary()
    if not binary:
        sys.stderr.write("Gemini CLI executable was not found\n")
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
        "--model", model,
        "--approval-mode", "auto_edit",
        "--sandbox",
    ]


def _event_summary(event: Mapping[str, Any]) -> tuple[str, str, float | None, dict[str, Any], bool, bool]:
    event_type = str(event.get("type") or event.get("event") or "unknown")
    payload: dict[str, Any] = {"vendor_event_type": event_type}
    lowered = event_type.lower()
    completed = False
    fatal = False
    if lowered == "init":
        payload["session_id"] = event.get("session_id") or event.get("sessionId")
        payload["model"] = event.get("model")
        return "gemini-session", "Gemini session initialized.", 10.0, payload, False, False
    if lowered == "message":
        payload["role"] = event.get("role")
        payload["content"] = str(event.get("content") or event.get("message") or "")[:2000]
        return "gemini-message", "Gemini emitted a message event.", 45.0, payload, False, False
    if lowered == "tool_use":
        payload["tool"] = str(event.get("name") or event.get("tool_name") or "tool")[:200]
        return "gemini-tool", "Gemini requested a workspace tool.", 55.0, payload, False, False
    if lowered == "tool_result":
        payload["tool"] = str(event.get("name") or event.get("tool_name") or "tool")[:200]
        payload["status"] = event.get("status")
        return "gemini-tool-result", "Gemini completed a workspace tool.", 68.0, payload, False, False
    if lowered == "error":
        payload["error"] = str(event.get("error") or event.get("message") or "Gemini error")[:2000]
        severity = str(event.get("severity") or "").lower()
        fatal = bool(event.get("fatal")) or severity in {"fatal", "error"}
        return ("gemini-failed" if fatal else "gemini-warning"), (
            "Gemini reported a terminal failure." if fatal else "Gemini emitted a non-terminal warning."
        ), None, payload, fatal, False
    if lowered == "result":
        payload["status"] = event.get("status")
        payload["stats"] = event.get("stats") or event.get("usage") or {}
        fatal = bool(event.get("error")) or str(event.get("status") or "").lower() in {"error", "failed"}
        if fatal:
            payload["error"] = str(event.get("error") or "Gemini result failed")[:2000]
            return "gemini-failed", "Gemini result reported failure.", None, payload, True, True
        completed = True
        return "gemini-completed", "Gemini stream completed.", 82.0, payload, False, completed
    return "gemini-event", f"Gemini event: {event_type}", None, payload, False, False


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
            raise GeminiDriverError("unsupported Aether task request")
        binary = _binary()
        if not binary:
            raise GeminiDriverError("Gemini CLI executable was not found")
        auth_ready, auth_mode = _auth_ready()
        key_file = _key_file()
        credentials_file = _credentials_file()
        if not auth_ready:
            raise GeminiDriverError("Gemini CLI authentication is not configured")
        workspace = Path(str(dict(request.get("workspace") or {}).get("root") or "")).resolve()
        if not workspace.is_dir():
            raise GeminiDriverError("staging workspace does not exist")
        limits = dict(request.get("limits") or {})
        max_files = min(DEFAULT_MAX_FILES, max(1, int(limits.get("maximum_files") or DEFAULT_MAX_FILES)))
        max_bytes = min(DEFAULT_MAX_TOTAL_BYTES, max(1, int(limits.get("maximum_total_bytes") or DEFAULT_MAX_TOTAL_BYTES)))
        max_frame_bytes = max(4096, int(limits.get("maximum_frame_bytes") or 65536))
        allowed = tuple(str(item) for item in dict(request.get("workspace") or {}).get("allowed_relative_paths") or (".",))
        before = snapshot(workspace, allowed, max_files=max(500, max_files * 20), max_bytes=52_428_800)
        model = _model()
        writer.emit("task.accepted", {
            "phase": "driver", "message": "Gemini CLI driver accepted the staging task.", "percent": 2.0,
            "driver_id": DRIVER_ID, "auth_mode": auth_mode, "model_id": model,
        })
        prompt = coding_prompt(request, vendor="Gemini CLI", denied_surfaces="Do not use shell, web, MCP, or delegation tools.")
        max_events = max(1, int(os.environ.get("AETHER_GEMINI_MAX_EVENTS", DEFAULT_MAX_EVENTS)))
        max_output = max(1024, int(os.environ.get("AETHER_GEMINI_MAX_OUTPUT_BYTES", DEFAULT_MAX_OUTPUT_BYTES)))
        secrets = [read_secret(key_file)]
        with tempfile.TemporaryDirectory(prefix="aether-gemini-run-") as vendor_root_raw, tempfile.TemporaryDirectory(prefix="aether-gemini-home-") as isolated_home_raw:
            vendor_root = Path(vendor_root_raw) / "workspace"
            isolated_home = Path(isolated_home_raw)
            shutil.copytree(workspace, vendor_root, ignore=shutil.ignore_patterns(".git", ".gemini", ".agents", "__pycache__", ".pytest_cache"))
            proc = await asyncio.create_subprocess_exec(
                *_argv(binary, prompt, model), cwd=str(vendor_root),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env=_vendor_env(isolated_home=isolated_home, key_file=key_file, credentials_file=credentials_file),
                limit=1_048_576,
            )
            assert proc.stdout is not None and proc.stderr is not None
            stderr_task = asyncio.create_task(proc.stderr.read(max_output + 1))
            events = 0; output_bytes = 0; fatal: str | None = None; completed = False
            normalized = 0; suppressed = 0
            max_normalized = max(20, int(os.environ.get("AETHER_GEMINI_MAX_NORMALIZED_FRAMES", "400")))
            while True:
                raw = await proc.stdout.readline()
                if not raw:
                    break
                events += 1; output_bytes += len(raw)
                if events > max_events or output_bytes > max_output:
                    proc.kill(); raise GeminiDriverError("Gemini stream exceeds driver limits")
                try:
                    event = json.loads(raw.decode("utf-8", errors="strict"))
                except Exception as exc:
                    proc.kill(); raise GeminiDriverError("Gemini emitted malformed JSONL") from exc
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
                raise GeminiDriverError("Gemini stderr exceeds driver limits")
            stderr_text = redact_text(stderr.decode(errors="replace"), secrets)
            if exit_code != 0:
                raise GeminiDriverError(f"Gemini CLI exited with code {exit_code}: {stderr_text[-2000:]}")
            if fatal:
                raise GeminiDriverError(fatal)
            if not completed:
                raise GeminiDriverError("Gemini stream ended without a result event")
            if suppressed:
                writer.emit("task.progress", {
                    "phase": "gemini-stream-summary",
                    "message": f"Suppressed {suppressed} low-priority vendor events after normalization limit.",
                    "percent": 84.0, "metadata": {"suppressed_vendor_events": suppressed},
                })
            after = snapshot(vendor_root, allowed, max_files=max(500, max_files * 20), max_bytes=52_428_800)
        patch_files = emit_patches(
            writer, before=before, after=after, max_files=max_files, max_bytes=max_bytes,
            max_frame_bytes=max_frame_bytes, driver_id=DRIVER_ID, vendor="Google Gemini CLI", model_id=model,
        )
        writer.emit("task.completed", {
            "ok": True, "phase": "driver-completed", "message": "Gemini patch translated for Aether verification.",
            "patch_files": patch_files, "driver_id": DRIVER_ID, "model_id": model,
        })
        return 0
    except (GeminiDriverError, DriverBoundaryError, Exception) as exc:
        writer.emit("task.error", {"error": f"{type(exc).__name__}: {exc}", "driver_id": DRIVER_ID})
        return 1


async def _main() -> int:
    if "--aether-handshake" in sys.argv:
        return await handshake()
    if "--aether-run" in sys.argv:
        return await run_task()
    sys.stderr.write("Usage: python -m aether_gateway.runtime_drivers.gemini_cli --aether-handshake|--aether-run\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
