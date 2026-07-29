"""OpenAI Codex CLI translator for Aether JSONL Streaming Protocol v1.

This module is an external-process driver. It receives one Aether task.start
request, runs Codex CLI in non-interactive JSONL mode inside the staging
workspace, normalizes progress, and emits complete-text patch frames. The
parent Aether adapter independently validates, verifies, and applies patches.
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

DRIVER_ID = "openai-codex-cli"
RUNTIME_ID = "openai.codex-cli"
DEFAULT_MAX_EVENTS = 2000
DEFAULT_MAX_OUTPUT_BYTES = 4_194_304
DEFAULT_MAX_FILES = 20
DEFAULT_MAX_TOTAL_BYTES = 524_288
IGNORED_PARTS = {".git", ".codex", ".agents", "__pycache__", ".pytest_cache", ".mypy_cache", "node_modules"}


class CodexDriverError(RuntimeError):
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


def _codex_binary() -> str | None:
    configured = os.environ.get("AETHER_CODEX_BIN", "").strip()
    if configured:
        resolved = shutil.which(configured) if not Path(configured).is_absolute() else configured
        return str(resolved) if resolved and Path(resolved).exists() else None
    return shutil.which("codex")


def _codex_home() -> Path:
    configured = os.environ.get("AETHER_CODEX_HOME", "").strip() or os.environ.get("CODEX_HOME", "").strip()
    return Path(configured).expanduser().resolve() if configured else (Path.home() / ".codex").resolve()


def _auth_ready() -> tuple[bool, str]:
    if os.environ.get("AETHER_CODEX_DRIVER_ALLOW_UNAUTHENTICATED", "").strip() == "1":
        return True, "test-override"
    if os.environ.get("OPENAI_API_KEY", "").strip():
        return True, "api-key"
    home = _codex_home()
    for name in ("auth.json", "credentials.json"):
        if (home / name).is_file():
            return True, "codex-home"
    return False, "missing-auth"


async def _version(binary: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        binary, "--version", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env=_vendor_env(),
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
    except asyncio.TimeoutError as exc:
        proc.kill(); await proc.communicate()
        raise CodexDriverError("Codex CLI version discovery timed out") from exc
    if proc.returncode != 0:
        raise CodexDriverError(f"Codex CLI version discovery failed: {stderr.decode(errors='replace')[-1000:]}")
    value = stdout.decode("utf-8", errors="replace").strip()
    if not value:
        raise CodexDriverError("Codex CLI returned an empty version")
    return value[:200]


def _vendor_env(*, isolated_home: str | None = None) -> dict[str, str]:
    allowed = {
        "PATH", "SYSTEMROOT", "WINDIR", "TMP", "TEMP", "LANG", "LC_ALL",
        "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_ORGANIZATION", "OPENAI_PROJECT",
        "SSL_CERT_FILE", "SSL_CERT_DIR", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
    }
    env = {key: value for key, value in os.environ.items() if key in allowed and value}
    codex_home = _codex_home()
    env["CODEX_HOME"] = str(codex_home)
    if isolated_home:
        env["HOME"] = isolated_home
        env["USERPROFILE"] = isolated_home
    env["CI"] = "1"
    env["NO_COLOR"] = "1"
    return env


def _handshake_payload(version: str, auth_ready: bool, auth_mode: str) -> dict[str, Any]:
    return {
        "protocol": AETHER_CODING_STREAM_PROTOCOL,
        "runtime": {
            "id": RUNTIME_ID,
            "version": version,
            "display_name": "OpenAI Codex CLI Driver",
            "operations": ["coding.task.execute"],
            "capabilities": ["coding.edit", "coding.verify", "coding.patch-generation", "coding.artifact-return"],
            "features": [
                "external-cli", "jsonl-stream-v1", "vendor-driver-pack-v1", "codex-exec-jsonl",
                "generative-coding", "runtime-generated-patch", "independent-verification",
                "workspace-binding", "progress-events", "bounded-artifacts", "verification-receipts", "no-shell",
            ],
            "metadata": {
                "driver_id": DRIVER_ID,
                "vendor": "OpenAI",
                "vendor_event_protocol": "codex.exec-jsonl",
                "auth_ready": auth_ready,
                "auth_mode": auth_mode,
                "degraded": not auth_ready,
                "authority": "body_only",
            },
        },
        "limits": {"max_frame_bytes": 1_048_576, "max_patch_files": DEFAULT_MAX_FILES},
    }



async def handshake() -> int:
    binary = _codex_binary()
    if not binary:
        sys.stderr.write("Codex CLI executable was not found\n")
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
            raise CodexDriverError(f"invalid allowed path: {raw}")
        candidate = (root / rel).resolve()
        if candidate != root and root not in candidate.parents:
            raise CodexDriverError(f"allowed path escapes workspace: {raw}")
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
                raise CodexDriverError("workspace snapshot exceeds driver limits")
            result[rel] = (hashlib.sha256(data).hexdigest(), text)
    return result


def _prompt(request: Mapping[str, Any]) -> str:
    task = dict(request.get("task") or {})
    objective = str(task.get("objective") or "").strip()
    if not objective:
        raise CodexDriverError("coding objective is required")
    allowed = list(dict(request.get("workspace") or {}).get("allowed_relative_paths") or ["."])
    return (
        "You are operating as a replaceable coding body for Aether OS.\n"
        "Work only inside the current staging workspace. Do not access or modify parent paths, .git, .codex, or .agents.\n"
        "Do not ask for interactive approval. Make the smallest correct source change needed for the objective.\n"
        "Aether will independently verify all changes and may reject them. Do not claim success unless the workspace is actually edited.\n"
        f"Allowed relative paths: {json.dumps(allowed)}\n"
        f"Objective: {objective}\n"
        "Finish with a concise summary of files changed."
    )


def _codex_argv(binary: str) -> list[str]:
    argv = [
        binary,
        "--ask-for-approval", "never",
        "--sandbox", "workspace-write",
        "exec",
        "--json",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        "--color", "never",
    ]
    model = os.environ.get("AETHER_CODEX_MODEL", "").strip()
    if model:
        argv.extend(["--model", model])
    argv.append("-")
    return argv


def _event_summary(event: Mapping[str, Any]) -> tuple[str, str, float | None, dict[str, Any], bool]:
    event_type = str(event.get("type") or "unknown")
    payload: dict[str, Any] = {"vendor_event_type": event_type}
    fatal = False
    if event_type == "thread.started":
        payload["thread_id"] = event.get("thread_id") or event.get("thread", {}).get("id")
        return "codex-thread", "Codex thread started.", 10.0, payload, False
    if event_type == "turn.started":
        return "codex-turn", "Codex generation turn started.", 20.0, payload, False
    if event_type in {"item.started", "item.updated", "item.completed"}:
        item = dict(event.get("item") or {})
        item_type = str(item.get("type") or "item")
        payload["item_type"] = item_type
        if item_type == "command_execution":
            command = item.get("command") or item.get("aggregated_output") or ""
            return "codex-command", f"Codex command event: {str(command)[:500]}", 45.0, payload, False
        if item_type in {"file_change", "file_update"}:
            return "codex-edit", "Codex reported a file change.", 65.0, payload, False
        if item_type == "agent_message":
            text = item.get("text") or item.get("message") or ""
            payload["message"] = str(text)[:2000]
            return "codex-message", "Codex produced an agent message.", 75.0, payload, False
        if item_type == "reasoning":
            return "codex-reasoning", "Codex produced a reasoning summary.", 35.0, payload, False
        if item_type == "error":
            # Codex can emit non-fatal item-level stream errors and still complete.
            payload["warning"] = str(item.get("message") or item.get("error") or "vendor item error")[:1000]
            return "codex-warning", "Codex emitted a non-terminal item warning.", None, payload, False
        return "codex-item", f"Codex item event: {item_type}", None, payload, False
    if event_type == "turn.completed":
        payload["usage"] = dict(event.get("usage") or {})
        return "codex-completed", "Codex turn completed.", 80.0, payload, False
    if event_type in {"turn.failed", "error"}:
        payload["error"] = str(event.get("error") or event.get("message") or "Codex turn failed")[:2000]
        return "codex-failed", "Codex turn failed.", None, payload, True
    return "codex-event", f"Codex event: {event_type}", None, payload, False


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
            raise CodexDriverError("unsupported Aether task request")
        binary = _codex_binary()
        if not binary:
            raise CodexDriverError("Codex CLI executable was not found")
        auth_ready, auth_mode = _auth_ready()
        if not auth_ready:
            raise CodexDriverError("Codex CLI authentication is not configured")
        workspace = Path(str(dict(request.get("workspace") or {}).get("root") or "")).resolve()
        if not workspace.is_dir():
            raise CodexDriverError("staging workspace does not exist")
        limits = dict(request.get("limits") or {})
        max_files = min(DEFAULT_MAX_FILES, max(1, int(limits.get("maximum_files") or DEFAULT_MAX_FILES)))
        max_bytes = min(DEFAULT_MAX_TOTAL_BYTES, max(1, int(limits.get("maximum_total_bytes") or DEFAULT_MAX_TOTAL_BYTES)))
        max_frame_bytes = max(4096, int(limits.get("maximum_frame_bytes") or 65536))
        allowed = tuple(str(item) for item in dict(request.get("workspace") or {}).get("allowed_relative_paths") or (".",))
        before = _snapshot(workspace, allowed, max_files=max(500, max_files * 20), max_bytes=52_428_800)
        writer.emit("task.accepted", {"phase": "driver", "message": "Codex CLI driver accepted the staging task.", "percent": 2.0,
                                      "driver_id": DRIVER_ID, "auth_mode": auth_mode})
        prompt = _prompt(request)
        max_events = max(1, int(os.environ.get("AETHER_CODEX_MAX_EVENTS", DEFAULT_MAX_EVENTS)))
        max_output = max(1024, int(os.environ.get("AETHER_CODEX_MAX_OUTPUT_BYTES", DEFAULT_MAX_OUTPUT_BYTES)))
        with tempfile.TemporaryDirectory(prefix="aether-codex-run-") as vendor_root_raw, tempfile.TemporaryDirectory(prefix="aether-codex-home-") as isolated_home:
            vendor_root = Path(vendor_root_raw) / "workspace"
            shutil.copytree(workspace, vendor_root, ignore=shutil.ignore_patterns(".git", ".codex", ".agents", "__pycache__", ".pytest_cache"))
            proc = await asyncio.create_subprocess_exec(
                *_codex_argv(binary), cwd=str(vendor_root), stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env=_vendor_env(isolated_home=isolated_home), limit=1_048_576,
            )
            assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None
            proc.stdin.write(prompt.encode("utf-8")); await proc.stdin.drain(); proc.stdin.close()
            stderr_task = asyncio.create_task(proc.stderr.read(max_output + 1))
            events = 0; output_bytes = 0; turn_completed = False; fatal: str | None = None
            normalized = 0; suppressed = 0; max_normalized = max(20, int(os.environ.get("AETHER_CODEX_MAX_NORMALIZED_FRAMES", "400")))
            while True:
                raw = await proc.stdout.readline()
                if not raw:
                    break
                events += 1; output_bytes += len(raw)
                if events > max_events or output_bytes > max_output:
                    proc.kill(); raise CodexDriverError("Codex JSONL stream exceeds driver limits")
                try:
                    event = json.loads(raw.decode("utf-8", errors="strict"))
                except Exception as exc:
                    proc.kill(); raise CodexDriverError("Codex emitted malformed JSONL") from exc
                phase, message, percent, metadata, event_fatal = _event_summary(event)
                if str(event.get("type") or "") == "turn.completed":
                    turn_completed = True
                if event_fatal:
                    fatal = str(metadata.get("error") or message)
                if normalized < max_normalized or event_fatal or str(event.get("type") or "") == "turn.completed":
                    writer.emit("task.progress", {"phase": phase, "message": message, "percent": percent, "metadata": metadata})
                    normalized += 1
                else:
                    suppressed += 1
            exit_code = await proc.wait()
            stderr = await stderr_task
            if len(stderr) > max_output:
                raise CodexDriverError("Codex stderr exceeds driver limits")
            if exit_code != 0:
                raise CodexDriverError(f"Codex CLI exited with code {exit_code}: {stderr.decode(errors='replace')[-2000:]}")
            if fatal:
                raise CodexDriverError(fatal)
            if not turn_completed:
                raise CodexDriverError("Codex stream ended without turn.completed")
            if suppressed:
                writer.emit("task.progress", {"phase": "codex-stream-summary", "message": f"Suppressed {suppressed} low-priority vendor events after normalization limit.", "percent": 82.0, "metadata": {"suppressed_vendor_events": suppressed}})
            after = _snapshot(vendor_root, allowed, max_files=max(500, max_files * 20), max_bytes=52_428_800)
        changed = sorted(set(before) | set(after))
        patches: list[tuple[str, str, str | None]] = []
        total = 0
        for path in changed:
            old = before.get(path); new = after.get(path)
            if old == new:
                continue
            if new is None:
                raise CodexDriverError(f"Codex deleted {path}; deletion is not supported by protocol v1")
            content = new[1]; content_bytes = len(content.encode("utf-8")); total += content_bytes
            if content_bytes > max_frame_bytes - 4096:
                raise CodexDriverError(f"generated file exceeds protocol v1 frame limit: {path}")
            if len(patches) >= max_files or total > max_bytes:
                raise CodexDriverError("Codex generated patch exceeds task limits")
            patches.append((path, content, old[0] if old else None))
        if not patches:
            raise CodexDriverError("Codex completed without producing a workspace patch")
        for path, content, before_hash in patches:
            writer.emit("artifact.patch", {
                "path": path, "content": content, "before_sha256": before_hash, "kind": "upsert",
                "metadata": {"driver_id": DRIVER_ID, "vendor": "OpenAI", "authoritative_diff": False},
            })
        writer.emit("task.completed", {"ok": True, "phase": "driver-completed", "message": "Codex patch translated for Aether verification.",
                                       "patch_files": len(patches), "driver_id": DRIVER_ID})
        return 0
    except Exception as exc:
        writer.emit("task.error", {"error": f"{type(exc).__name__}: {exc}", "driver_id": DRIVER_ID})
        return 1


async def _main() -> int:
    if "--aether-handshake" in sys.argv:
        return await handshake()
    if "--aether-run" in sys.argv:
        return await run_task()
    sys.stderr.write("Usage: python -m aether_gateway.runtime_drivers.codex_cli --aether-handshake|--aether-run\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
