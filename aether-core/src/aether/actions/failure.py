"""Durable repeated-failure fingerprints for action retry governance."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from aether.contracts.actions import ActionProposal
from aether.utils.jsonio import append_jsonl, read_jsonl
from aether.utils.time import utc_now


def action_signature(proposal: ActionProposal) -> str:
    canonical = json.dumps({
        "target": str(proposal.target),
        "operation": proposal.operation,
        "arguments": dict(proposal.arguments),
        "scopes": sorted(str(scope) for scope in proposal.required_scopes),
    }, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class FailureFingerprintStore:
    def __init__(self, path: Path):
        self.path = path

    def open_failures(self, proposal: ActionProposal) -> list[dict[str, Any]]:
        signature = action_signature(proposal)
        state: dict[str, dict[str, Any]] = {}
        for row in read_jsonl(self.path):
            fingerprint = str(row.get("fingerprint") or "")
            if not fingerprint:
                continue
            state[fingerprint] = row
        return [row for row in state.values() if row.get("signature") == signature and row.get("status") == "open"]

    def record(self, proposal: ActionProposal, *, error_type: str, error: str) -> str:
        signature = action_signature(proposal)
        raw = f"{signature}:{error_type}:{error}".encode("utf-8")
        fingerprint = hashlib.sha256(raw).hexdigest()
        append_jsonl(self.path, {
            "fingerprint": fingerprint,
            "signature": signature,
            "status": "open",
            "action_id": proposal.action_id,
            "target": str(proposal.target),
            "operation": proposal.operation,
            "error_type": error_type,
            "error": error,
            "timestamp": utc_now(),
        })
        return fingerprint

    def resolve_signature(self, proposal: ActionProposal, *, resolution: str) -> None:
        for row in self.open_failures(proposal):
            append_jsonl(self.path, {
                **row,
                "status": "resolved",
                "resolution": resolution,
                "resolved_at": utc_now(),
            })
