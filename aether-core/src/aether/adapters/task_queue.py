"""Simple JSONL task queue for mind→body run_task handoff."""
from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


class TaskQueue:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "run_tasks.jsonl"

    def enqueue(self, goal: str, max_amount_usd: float = 0.0, context: Dict[str, Any] | None = None) -> str:
        tid = uuid.uuid4().hex[:12]
        row = {
            "task_id": tid,
            "goal": goal,
            "max_amount_usd": max_amount_usd,
            "context": context or {},
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        return tid

    def list_pending(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("status") == "pending":
                out.append(row)
        return out

    def complete(self, task_id: str, result: str = "") -> None:
        if not self.path.exists():
            return
        rows = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("task_id") == task_id:
                row["status"] = "done"
                row["result"] = result
            rows.append(row)
        self.path.write_text(
            "\n".join(json.dumps(r) for r in rows) + ("\n" if rows else ""),
            encoding="utf-8",
        )
