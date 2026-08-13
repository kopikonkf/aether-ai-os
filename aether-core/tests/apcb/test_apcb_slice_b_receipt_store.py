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

        loaded = store.get_by_components("MISSION-1", "WORK-1", 1, "qwen")
        assert loaded is not None
        assert loaded.work_id == "WORK-1"
        assert loaded.attempt_number == 1
        assert loaded.principal_id == "qwen"
        assert loaded.mission_id == "MISSION-1"
        assert loaded.state is ExecutionReceiptStatus.CLAIMED

    def test_key_matches_idempotency_tuple(self):
        receipt = make_receipt()
        assert receipt.idempotency_key.as_tuple() == ("MISSION-1", "WORK-1", 1, "qwen")
        key = execution_receipt_key("MISSION-1", "WORK-1", 1, "qwen")
        assert key.as_tuple() == ("MISSION-1", "WORK-1", 1, "qwen")

    def test_append_only_log_reconstructs_after_restart(self, tmp_path):
        path = tmp_path / "receipts.jsonl"
        store1 = ReceiptStore(path)
        store1.persist(make_receipt(state=ExecutionReceiptStatus.CLAIMED))
        store1.persist(make_receipt(attempt=2, state=ExecutionReceiptStatus.TERMINAL))

        # Simulate APCB restart: new store instance on the same file.
        store2 = ReceiptStore(path)
        assert len(store2) == 2
        assert store2.get_by_components("MISSION-1", "WORK-1", 2, "qwen") is not None
        assert store2.get_by_components("MISSION-1", "WORK-1", 2, "qwen").is_terminal()

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
            assert record["receipt"]["mission_id"] == "MISSION-1"

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
        assert store.get_by_components("MISSION-1", "WORK-1", 1, "qwen").state is ExecutionReceiptStatus.PROMPTED

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
        latest = store.latest_for_work("WORK-1", mission_id="MISSION-1")
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


class TestCrossMissionExecutionIdentity:
    """P2-F01: the idempotency key is the ExecutionIdentity canonical tuple
    (mission_id, work_id, attempt_number, principal_id). MISSION-A WORK-X
    attempt-1 qwen and MISSION-B WORK-X attempt-1 qwen are two DISTINCT
    executions and never collide.
    """

    def test_same_work_different_missions_no_collision(self, tmp_path):
        store = ReceiptStore(tmp_path / "receipts.jsonl")
        a = make_receipt(mission="MISSION-A", work_id="WORK-X", attempt=1, principal="qwen")
        b = make_receipt(mission="MISSION-B", work_id="WORK-X", attempt=1, principal="qwen")
        store.persist(a)
        store.persist(b)

        assert len(store) == 2
        got_a = store.get_by_components("MISSION-A", "WORK-X", 1, "qwen")
        got_b = store.get_by_components("MISSION-B", "WORK-X", 1, "qwen")
        assert got_a is not None and got_a.mission_id == "MISSION-A"
        assert got_b is not None and got_b.mission_id == "MISSION-B"
        assert got_a is not got_b

    def test_same_work_terminal_in_one_mission_does_not_block_other(self, tmp_path):
        store = ReceiptStore(tmp_path / "receipts.jsonl")
        # MISSION-A WORK-X attempt-1 is terminal
        store.persist(
            make_receipt(
                mission="MISSION-A", work_id="WORK-X", attempt=1, principal="qwen",
                state=ExecutionReceiptStatus.TERMINAL,
            )
        )
        # MISSION-B WORK-X attempt-1 has no active attempt in ITS mission
        assert not store.has_active_attempt("WORK-X", "qwen", mission_id="MISSION-B")
        # MISSION-A has no active attempt either (its attempt-1 is terminal)
        assert not store.has_active_attempt("WORK-X", "qwen", mission_id="MISSION-A")

    def test_same_work_active_in_other_mission_scoped_away(self, tmp_path):
        store = ReceiptStore(tmp_path / "receipts.jsonl")
        store.persist(
            make_receipt(
                mission="MISSION-A", work_id="WORK-X", attempt=1, principal="qwen",
                state=ExecutionReceiptStatus.CLAIMED,
            )
        )
        # MISSION-B WORK-X attempt-1 is free even though MISSION-A is active
        assert store.has_active_attempt("WORK-X", "qwen", mission_id="MISSION-A")
        assert not store.has_active_attempt("WORK-X", "qwen", mission_id="MISSION-B")

    def test_latest_for_work_is_mission_scoped(self, tmp_path):
        store = ReceiptStore(tmp_path / "receipts.jsonl")
        store.persist(make_receipt(mission="MISSION-A", work_id="WORK-X", attempt=1, state=ExecutionReceiptStatus.TERMINAL))
        store.persist(make_receipt(mission="MISSION-B", work_id="WORK-X", attempt=5, state=ExecutionReceiptStatus.CLAIMED))
        # Within MISSION-A the highest attempt is 1; MISSION-B's attempt 5 is not
        # MISSION-A's business.
        assert store.latest_for_work("WORK-X", mission_id="MISSION-A").attempt_number == 1
        assert store.latest_for_work("WORK-X", mission_id="MISSION-B").attempt_number == 5
