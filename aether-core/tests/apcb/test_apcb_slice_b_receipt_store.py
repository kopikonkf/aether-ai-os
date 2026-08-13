"""APCB Slice B — receipt store durability + idempotency tuple.

Contract section 5: the bridge persists its own execution receipt keyed by
(work_id, attempt_number, principal_id) BEFORE dispatch, and reconciles the
existing receipt on poll/restart/reconnect before dispatching again.
"""
from __future__ import annotations

import json

import pytest

from aether.apcb.contracts import (
    BridgeExecutionReceipt,
    ExecutionReceiptStatus,
    execution_receipt_key,
)
from aether.apcb.receipt_store import ReceiptStore


def make_receipt(
    work_id="WORK-1",
    attempt=1,
    principal="qwen",
    mission="MISSION-1",
    state=ExecutionReceiptStatus.DISCOVERED,
):
    return BridgeExecutionReceipt(
        work_id=work_id,
        attempt_number=attempt,
        principal_id=principal,
        mission_id=mission,
        state=state,
    )


class TestReceiptPersistence:
    def test_persist_then_load_roundtrip(self, tmp_path):
        store = ReceiptStore(tmp_path / "receipts.jsonl")
        receipt = make_receipt(state=ExecutionReceiptStatus.CLAIMED)
        store.persist(receipt)

        loaded = store.get_by_components("WORK-1", 1, "qwen")
        assert loaded is not None
        assert loaded.work_id == "WORK-1"
        assert loaded.attempt_number == 1
        assert loaded.principal_id == "qwen"
        assert loaded.mission_id == "MISSION-1"
        assert loaded.state is ExecutionReceiptStatus.CLAIMED

    def test_key_matches_idempotency_tuple(self):
        receipt = make_receipt()
        assert receipt.idempotency_key.as_tuple() == ("WORK-1", 1, "qwen")
        key = execution_receipt_key("WORK-1", 1, "qwen")
        assert key.as_tuple() == ("WORK-1", 1, "qwen")

    def test_append_only_log_reconstructs_after_restart(self, tmp_path):
        path = tmp_path / "receipts.jsonl"
        store1 = ReceiptStore(path)
        store1.persist(make_receipt(state=ExecutionReceiptStatus.CLAIMED))
        store1.persist(make_receipt(attempt=2, state=ExecutionReceiptStatus.TERMINAL))

        # Simulate APCB restart: new store instance on the same file.
        store2 = ReceiptStore(path)
        assert len(store2) == 2
        assert store2.get_by_components("WORK-1", 2, "qwen") is not None
        assert store2.get_by_components("WORK-1", 2, "qwen").is_terminal()

    def test_log_file_is_append_only_jsonl(self, tmp_path):
        path = tmp_path / "receipts.jsonl"
        store = ReceiptStore(path)
        store.persist(make_receipt())
        store.persist(make_receipt(attempt=3))
        lines = path.read_text("utf-8").splitlines()
        assert len(lines) == 2
        for line in lines:
            record = json.loads(line)
            assert record["receipt"]["work_id"] == "WORK-1"
            assert record["receipt"]["principal_id"] == "qwen"

    def test_corrupt_trailing_line_is_tolerated(self, tmp_path):
        path = tmp_path / "receipts.jsonl"
        store = ReceiptStore(path)
        store.persist(make_receipt(state=ExecutionReceiptStatus.CLAIMED))
        with path.open("a", encoding="utf-8") as f:
            f.write("{not-json\n")
        reloaded = ReceiptStore(path)
        assert len(reloaded) == 1  # corrupt line skipped, not fatal


class TestReceiptStateMachine:
    def test_is_terminal(self):
        terminal = make_receipt(state=ExecutionReceiptStatus.TERMINAL)
        assert terminal.is_terminal()
        non_terminal = make_receipt(state=ExecutionReceiptStatus.DISPATCHED if False else ExecutionReceiptStatus.PROMPTED)
        assert not non_terminal.is_terminal()

    def test_update_appends_new_snapshot(self, tmp_path):
        store = ReceiptStore(tmp_path / "r.jsonl")
        receipt = store.persist(make_receipt(state=ExecutionReceiptStatus.CLAIMED))
        updated = store.update(receipt, state=ExecutionReceiptStatus.PROMPTED)
        assert updated.state is ExecutionReceiptStatus.PROMPTED
        # Both snapshots are in the append-only log (index keeps latest per key).
        lines = [json.loads(l)["receipt"] for l in (tmp_path / "r.jsonl").read_text("utf-8").splitlines() if l.strip()]
        assert [l["state"] for l in lines] == ["claimed", "prompted"]
        assert store.get_by_components("WORK-1", 1, "qwen").state is ExecutionReceiptStatus.PROMPTED

    def test_observed_at_is_set_on_update(self, tmp_path):
        store = ReceiptStore(tmp_path / "r.jsonl")
        receipt = store.persist(make_receipt(state=ExecutionReceiptStatus.CLAIMED))
        assert receipt.observed_at is None or receipt.observed_at
        updated = store.update(receipt, state=ExecutionReceiptStatus.PROMPTED)
        assert updated.observed_at is not None


class TestReceiptQueries:
    def test_latest_for_work(self, tmp_path):
        store = ReceiptStore(tmp_path / "r.jsonl")
        store.persist(make_receipt(attempt=1, state=ExecutionReceiptStatus.TERMINAL))
        store.persist(make_receipt(attempt=2, state=ExecutionReceiptStatus.CLAIMED))
        latest = store.latest_for_work("WORK-1")
        assert latest is not None
        assert latest.attempt_number == 2

    def test_has_active_attempt(self, tmp_path):
        store = ReceiptStore(tmp_path / "r.jsonl")
        assert not store.has_active_attempt("WORK-1", "qwen")
        store.persist(make_receipt(attempt=1, state=ExecutionReceiptStatus.CLAIMED))
        assert store.has_active_attempt("WORK-1", "qwen")
        store.persist(make_receipt(attempt=1, state=ExecutionReceiptStatus.TERMINAL))
        assert not store.has_active_attempt("WORK-1", "qwen")

    def test_attempts_are_distinct_ownership(self, tmp_path):
        store = ReceiptStore(tmp_path / "r.jsonl")
        store.persist(make_receipt(attempt=1, principal="qwen", state=ExecutionReceiptStatus.TERMINAL))
        # qwen's attempt 1 is terminal; a different principal's active attempt is separate
        assert not store.has_active_attempt("WORK-1", "qwen")
        store.persist(make_receipt(attempt=1, principal="claude", state=ExecutionReceiptStatus.CLAIMED))
        assert store.has_active_attempt("WORK-1", "claude")
