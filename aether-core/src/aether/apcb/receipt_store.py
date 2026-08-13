"""APCB receipt store — durable execution receipts keyed by idempotency tuple.

Contract reference: project-docs/architecture/APCB_V0_1_IMPLEMENTATION_CONTRACT.md
Section 5 (durable coordination identity) and section 11 (reconciliation rules).

The bridge must persist its own execution receipt keyed by the idempotency
tuple (work_id, attempt_number, principal_id) BEFORE asking Herdr to start
work, and consult the existing receipt on every poll/restart/reconnect before
dispatching again.

Storage is an append-only JSONL file; the in-memory index is recomputed from
the log so a process restart never loses state (same pattern as the
capability-lifecycle tracker).
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path

from aether.apcb.contracts import (
    BridgeExecutionReceipt,
    ExecutionReceiptStatus,
    ReceiptIdempotencyKey,
    execution_receipt_key,
)


class ReceiptStore:
    """Append-only JSONL receipt store with an in-memory recomputed index.

    Thread-safety: the store is used by a single dispatcher; the file is
    appended atomically per record. Concurrent writers are not a supported
    APCB shape (one local bridge per host).
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._receipts: dict[tuple[str, int, str], BridgeExecutionReceipt] = {}
        self._recompute_from_log()

    # ------------------------------------------------------------------ #
    # Index (recomputed from log — restart-safe)                          #
    # ------------------------------------------------------------------ #
    def _recompute_from_log(self) -> None:
        if not self.path.exists():
            return
        for line in self.path.read_text("utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                receipt = _receipt_from_dict(rec["receipt"])
            except (json.JSONDecodeError, TypeError, KeyError, ValueError):
                continue  # tolerate a corrupt trailing line; never hard-fail
            self._receipts[receipt.idempotency_key.as_tuple()] = receipt

    # ------------------------------------------------------------------ #
    # Mutation                                                           #
    # ------------------------------------------------------------------ #
    def persist(self, receipt: BridgeExecutionReceipt) -> BridgeExecutionReceipt:
        """Append a receipt snapshot to the log and update the index.

        Must be called BEFORE dispatching to Herdr (contract section 5).
        """
        key = receipt.idempotency_key.as_tuple()
        record = {
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "receipt": _receipt_to_dict(receipt),
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            f.flush()
        self._receipts[key] = receipt
        return receipt

    def update(
        self,
        receipt: BridgeExecutionReceipt,
        *,
        state: ExecutionReceiptStatus | None = None,
        herdr_execution_ref: str | None = None,
        terminal_outcome: str | None = None,
        error: str | None = None,
    ) -> BridgeExecutionReceipt:
        """Return a new receipt with the given fields changed, then persist.

        The store is append-only: every state change appends a new snapshot so
        the full lifecycle is reconstructable from the log.
        """
        import dataclasses

        updated = dataclasses.replace(
            receipt,
            state=state or receipt.state,
            herdr_execution_ref=herdr_execution_ref
            if herdr_execution_ref is not None
            else receipt.herdr_execution_ref,
            terminal_outcome=terminal_outcome if terminal_outcome is not None else receipt.terminal_outcome,
            error=error if error is not None else receipt.error,
            observed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        return self.persist(updated)

    # ------------------------------------------------------------------ #
    # Reads                                                              #
    # ------------------------------------------------------------------ #
    def get(self, key: ReceiptIdempotencyKey) -> BridgeExecutionReceipt | None:
        return self._receipts.get(key.as_tuple())

    def get_by_components(
        self, work_id: str, attempt_number: int, principal_id: str
    ) -> BridgeExecutionReceipt | None:
        return self.get(execution_receipt_key(work_id, attempt_number, principal_id))

    def latest_for_work(self, work_id: str) -> BridgeExecutionReceipt | None:
        """Highest attempt_number receipt for a work item, or None."""
        matches = [
            r for key, r in self._receipts.items() if key[0] == work_id
        ]
        if not matches:
            return None
        return max(matches, key=lambda r: r.attempt_number)

    def has_active_attempt(self, work_id: str, principal_id: str) -> bool:
        """True when any non-terminal receipt owns this work+principal."""
        for key, receipt in self._receipts.items():
            if key[0] == work_id and key[2] == principal_id:
                if not receipt.is_terminal():
                    return True
        return False

    def all(self) -> list[BridgeExecutionReceipt]:
        return list(self._receipts.values())

    def __len__(self) -> int:
        return len(self._receipts)


def _receipt_to_dict(receipt: BridgeExecutionReceipt) -> dict:
    return asdict(receipt)


def _receipt_from_dict(data: dict) -> BridgeExecutionReceipt:
    return BridgeExecutionReceipt(
        work_id=data["work_id"],
        attempt_number=int(data["attempt_number"]),
        principal_id=data["principal_id"],
        mission_id=data["mission_id"],
        state=ExecutionReceiptStatus(data["state"]),
        herdr_execution_ref=data.get("herdr_execution_ref"),
        herdr_workspace_ref=data.get("herdr_workspace_ref"),
        correlation_id=data.get("correlation_id", ""),
        bridge_request_id=data.get("bridge_request_id", ""),
        observed_at=data.get("observed_at"),
        terminal_outcome=data.get("terminal_outcome"),
        error=data.get("error"),
        metadata=data.get("metadata") or {},
    )
