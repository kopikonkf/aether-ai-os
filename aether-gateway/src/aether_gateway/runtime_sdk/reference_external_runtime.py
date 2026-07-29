"""Reference external process implementing Aether JSONL Streaming Protocol v1.

This process is deliberately simple: it receives requested structured edits and
emits them as runtime-generated patch frames. It exists to prove the transport,
streaming, patch-ingestion, and verification boundaries. It is not Aether Core.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import sys
from pathlib import Path

from aether.contracts import AETHER_CODING_STREAM_PROTOCOL


RUNTIME_ID = "aether.reference-external-coding-runtime"
RUNTIME_VERSION = "0.1.0"


def emit(frame_type: str, task_id: str, sequence: int, payload: dict) -> None:
    sys.stdout.write(json.dumps({
        "type": frame_type,
        "protocol": AETHER_CODING_STREAM_PROTOCOL,
        "task_id": task_id,
        "sequence": sequence,
        "payload": payload,
    }, sort_keys=True) + "\n")
    sys.stdout.flush()


def handshake() -> int:
    print(json.dumps({
        "protocol": AETHER_CODING_STREAM_PROTOCOL,
        "runtime": {
            "id": RUNTIME_ID,
            "version": RUNTIME_VERSION,
            "display_name": "Aether Reference External Coding Runtime",
            "operations": ["coding.task.execute"],
            "capabilities": ["coding.edit", "coding.verify", "coding.patch-generation", "coding.artifact-return"],
            "features": [
                "external-cli", "jsonl-stream-v1", "runtime-generated-patch",
                "independent-verification", "structured-edits", "workspace-binding",
                "progress-events", "bounded-artifacts", "verification-receipts", "no-shell",
            ],
            "metadata": {"authority": "body_only", "reference": True},
        },
        "limits": {"max_frame_bytes": 65536, "max_patch_files": 10},
    }, sort_keys=True))
    return 0


def run_task() -> int:
    line = sys.stdin.readline()
    if not line:
        print("missing task request", file=sys.stderr)
        return 2
    request = json.loads(line)
    if request.get("protocol") != AETHER_CODING_STREAM_PROTOCOL:
        print("protocol mismatch", file=sys.stderr)
        return 3
    task = dict(request.get("task") or {})
    task_id = str(task.get("task_id") or "")
    if not task_id:
        print("task_id required", file=sys.stderr)
        return 4
    edits = [dict(item) for item in task.get("edits") or ()]
    emit("task.accepted", task_id, 1, {"phase": "accepted", "message": "External runtime accepted bounded task.", "percent": 5})
    emit("task.progress", task_id, 2, {"phase": "analysis", "message": "External runtime analyzed requested edits.", "percent": 25})
    sequence = 3
    for item in edits:
        relative = str(item.get("path") or "")
        path = Path(relative)
        before = path.read_text(encoding="utf-8") if path.exists() else ""
        before_hash = hashlib.sha256(before.encode("utf-8")).hexdigest() if path.exists() else None
        after = str(item.get("content") or "")
        diff = "".join(difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{relative}",
            tofile=f"b/{relative}",
        ))
        emit("artifact.patch", task_id, sequence, {
            "path": relative,
            "kind": "upsert",
            "before_sha256": before_hash,
            "content": after,
            "diff": diff,
            "metadata": {"generated_by": RUNTIME_ID},
        })
        sequence += 1
    emit("task.progress", task_id, sequence, {"phase": "patch", "message": f"Generated {len(edits)} patch artifact(s).", "percent": 80})
    sequence += 1
    emit("task.completed", task_id, sequence, {"ok": True, "patch_count": len(edits)})
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aether-handshake", action="store_true")
    parser.add_argument("--aether-run", action="store_true")
    args = parser.parse_args()
    if args.aether_handshake:
        return handshake()
    if args.aether_run:
        return run_task()
    parser.error("one protocol operation is required")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
