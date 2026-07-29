#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import platform
import sqlite3
from pathlib import Path


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"\'')
    return values


def safe_arguments(arguments: dict) -> dict:
    result = {"keys": sorted(map(str, arguments.keys()))}
    for key in ("path", "url", "op", "runtime_id"):
        if key in arguments:
            result[key] = str(arguments[key])
    if "content" in arguments or "_body" in arguments:
        content = str(arguments.get("content") or arguments.get("_body") or "")
        result["content_bytes"] = len(content.encode("utf-8"))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--approval-id")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    root = Path(args.release_root).resolve()
    env = read_env(root / "aether-core" / ".env")
    configured = env.get("AETHER_HOME") or os.environ.get("AETHER_HOME")
    if configured:
        home = Path(configured).expanduser()
    elif platform.system() == "Windows":
        home = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")) / "Aether"
    else:
        home = Path.home() / ".aether"
    db = home / "governance" / "pending-actions.sqlite3"
    output = {"aether_home": str(home), "approval_db": str(db), "records": []}
    if not db.exists():
        output["error"] = "approval database not found"
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return 1
    connection = sqlite3.connect(db)
    connection.row_factory = sqlite3.Row
    try:
        if args.approval_id:
            rows = connection.execute("SELECT * FROM pending_actions WHERE approval_id = ?", (args.approval_id,)).fetchall()
        else:
            rows = connection.execute("SELECT * FROM pending_actions ORDER BY requested_at DESC LIMIT ?", (max(1, args.limit),)).fetchall()
        for row in rows:
            proposal = json.loads(row["proposal_json"])
            result = json.loads(row["result_json"]) if row["result_json"] else None
            output["records"].append({
                "approval_id": row["approval_id"],
                "status": row["status"],
                "requested_at": row["requested_at"],
                "expires_at": row["expires_at"],
                "target": proposal.get("target"),
                "operation": proposal.get("operation"),
                "arguments": safe_arguments(dict(proposal.get("arguments") or {})),
                "reason": proposal.get("reason"),
                "decision_reason": row["decision_reason"],
                "result": None if result is None else {
                    "ok": result.get("ok"),
                    "status": result.get("status"),
                    "error": result.get("error"),
                    "failure_fingerprint": result.get("failure_fingerprint"),
                },
            })
    finally:
        connection.close()
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
