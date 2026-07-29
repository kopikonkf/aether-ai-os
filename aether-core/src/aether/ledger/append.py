from __future__ import annotations

from pathlib import Path
from typing import Any

from aether.ledger.hash_chain import AppendOnlyLedger


def append_ledger_entry(
    root: Path,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str,
    summary: str,
    evidence_links: list[str] | None = None,
    payload: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Legacy-compatible ledger append.

    Sprint 02 expected this function to write to:
    `runtime_state/ledger/ledger.jsonl`

    Sprint 03R keeps that path and adds hash-chain hardening.
    """
    ledger_path = root / "runtime_state" / "ledger" / "ledger.jsonl"
    return AppendOnlyLedger(ledger_path).append(
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        summary=summary,
        evidence_links=evidence_links or [],
        payload=payload or {},
        correlation_id=correlation_id,
    )
