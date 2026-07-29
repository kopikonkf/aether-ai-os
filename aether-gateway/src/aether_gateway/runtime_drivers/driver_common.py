"""Shared bounded helpers for vendor CLI translators.

These helpers know nothing about vendor authentication or event formats. They
only implement Aether-owned framing, workspace snapshotting, redaction, and
complete-text patch emission for protocol v1.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from aether.contracts import AETHER_CODING_STREAM_PROTOCOL

IGNORED_PARTS = {
    ".git", ".agents", ".aether", ".gemini", ".claude", ".opencode", ".codex",
    "__pycache__", ".pytest_cache", ".mypy_cache", "node_modules",
}


class DriverBoundaryError(RuntimeError):
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


def snapshot(root: Path, allowed: Sequence[str], *, max_files: int, max_bytes: int) -> dict[str, tuple[str, str]]:
    root = root.resolve()
    result: dict[str, tuple[str, str]] = {}
    total = 0
    starts: list[Path] = []
    for raw in allowed or (".",):
        rel = Path(str(raw))
        if rel.is_absolute() or ".." in rel.parts:
            raise DriverBoundaryError(f"invalid allowed path: {raw}")
        candidate = (root / rel).resolve()
        if candidate != root and root not in candidate.parents:
            raise DriverBoundaryError(f"allowed path escapes workspace: {raw}")
        starts.append(candidate)
    seen: set[Path] = set()
    for start in starts:
        if not start.exists():
            continue
        iterator = [start] if start.is_file() else start.rglob("*")
        for path in iterator:
            if not path.is_file() or path in seen:
                continue
            relative = path.relative_to(root)
            if any(part in IGNORED_PARTS for part in relative.parts):
                continue
            seen.add(path)
            data = path.read_bytes()
            if b"\x00" in data:
                continue
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                continue
            total += len(data)
            if len(result) >= max_files or total > max_bytes:
                raise DriverBoundaryError("workspace snapshot exceeds driver limits")
            result[relative.as_posix()] = (hashlib.sha256(data).hexdigest(), text)
    return result


def coding_prompt(request: Mapping[str, Any], *, vendor: str, denied_surfaces: str) -> str:
    task = dict(request.get("task") or {})
    objective = str(task.get("objective") or "").strip()
    if not objective:
        raise DriverBoundaryError("coding objective is required")
    allowed = list(dict(request.get("workspace") or {}).get("allowed_relative_paths") or ["."])
    return (
        f"You are {vendor}, operating only as a replaceable coding body for Aether OS. "
        "Work only inside the current disposable workspace. Do not access parent paths, credentials, "
        f".git, .agents, or external services. {denied_surfaces} "
        "Make the smallest correct source change needed for the objective. "
        "Aether independently verifies all bytes and may reject the result.\n"
        f"Allowed relative paths: {json.dumps(allowed)}\n"
        f"Objective: {objective}\n"
        "Edit the workspace directly and finish with a concise summary; do not merely describe a patch."
    )


def read_secret(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def redact_text(value: str, secrets: Sequence[str]) -> str:
    result = value
    for secret in secrets:
        if secret:
            result = result.replace(secret, "[REDACTED]")
    return result


def redact_mapping(value: Mapping[str, Any], secrets: Sequence[str]) -> dict[str, Any]:
    rendered = json.dumps(dict(value), sort_keys=True, default=str, ensure_ascii=False)
    return json.loads(redact_text(rendered, secrets))


def emit_patches(
    writer: FrameWriter,
    *,
    before: Mapping[str, tuple[str, str]],
    after: Mapping[str, tuple[str, str]],
    max_files: int,
    max_bytes: int,
    max_frame_bytes: int,
    driver_id: str,
    vendor: str,
    model_id: str,
) -> int:
    changed = sorted(set(before) | set(after))
    patches: list[tuple[str, str, str | None]] = []
    total = 0
    for path in changed:
        old = before.get(path)
        new = after.get(path)
        if old == new:
            continue
        if new is None:
            raise DriverBoundaryError(f"{vendor} deleted {path}; deletion is not supported by protocol v1")
        content = new[1]
        content_bytes = len(content.encode("utf-8"))
        total += content_bytes
        if content_bytes > max_frame_bytes - 4096:
            raise DriverBoundaryError(f"generated file exceeds protocol v1 frame limit: {path}")
        if len(patches) >= max_files or total > max_bytes:
            raise DriverBoundaryError(f"{vendor} generated patch exceeds task limits")
        patches.append((path, content, old[0] if old else None))
    if not patches:
        raise DriverBoundaryError(f"{vendor} completed without producing a workspace patch")
    for path, content, before_hash in patches:
        writer.emit("artifact.patch", {
            "path": path,
            "content": content,
            "before_sha256": before_hash,
            "kind": "upsert",
            "metadata": {
                "driver_id": driver_id,
                "vendor": vendor,
                "model_id": model_id,
                "authoritative_diff": False,
            },
        })
    return len(patches)
