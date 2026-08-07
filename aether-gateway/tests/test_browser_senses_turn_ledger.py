from __future__ import annotations

import importlib.util
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


MODULE_PATH = (
    Path(__file__).parents[1]
    / "src"
    / "aether_gateway"
    / "browser_senses"
    / "turns.py"
)
SPEC = importlib.util.spec_from_file_location("aether_gateway_browser_turns", MODULE_PATH)
assert SPEC and SPEC.loader
turns = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(turns)


class BrowserSenseTurnLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "turns.sqlite3"
        self.ledger = turns.BrowserSenseTurnLedger(self.path)

    def claim(self, **overrides):
        values = {
            "session_id": "session-1",
            "turn_id": "turn-1",
            "correlation_id": "corr-1",
            "generation": 0,
            "request_hash": "a" * 64,
            "retry_of_turn_id": None,
        }
        values.update(overrides)
        return self.ledger.claim(**values)

    def test_duplicate_exact_claim_never_authorizes_cognition_twice(self):
        first = self.claim()
        duplicate = self.claim()

        self.assertTrue(first.first_claim)
        self.assertFalse(duplicate.first_claim)
        self.assertEqual(duplicate.status["state"], "accepted")
        self.assertEqual(self.ledger.counts()["claims"], 1)
        self.assertEqual(self.ledger.counts()["events"], 1)

    def test_turn_id_is_bound_to_exact_session_correlation_and_request_hash(self):
        self.claim()
        for overrides in (
            {"session_id": "session-other"},
            {"correlation_id": "corr-other"},
            {"request_hash": "b" * 64},
            {"generation": 1},
        ):
            with self.assertRaises(turns.TurnClaimConflict):
                self.claim(**overrides)
        with self.assertRaises(ValueError):
            self.claim(turn_id="turn-new", generation=1)
        with self.assertRaises(ValueError):
            self.claim(turn_id="turn-self", retry_of_turn_id="turn-self")

    def test_terminal_completion_is_hash_only_and_session_scoped(self):
        self.claim()
        complete = self.ledger.complete(
            session_id="session-1",
            turn_id="turn-1",
            correlation_id="corr-1",
            generation=0,
            response_hash="b" * 64,
            terminal_receipt_id="sense-turn-receipt-1",
        )

        self.assertEqual(complete["state"], "completed")
        self.assertEqual(complete["response_hash"], "b" * 64)
        self.assertNotIn("response", complete)
        self.assertEqual(
            self.ledger.status(session_id="session-1", turn_id="turn-1"),
            complete,
        )
        with self.assertRaises(KeyError):
            self.ledger.status(session_id="session-other", turn_id="turn-1")

    def test_interruption_advances_generation_once_and_is_idempotent(self):
        self.claim()
        first = self.ledger.interrupt(
            session_id="session-1",
            turn_id="turn-1",
            correlation_id="corr-1",
            previous_generation=0,
            next_generation=1,
            reason="explicit_stop",
            provider_cancel_supported=True,
            provider_cancelled=True,
            delivered_audio_ms=120,
            browser_audio_stopped=True,
            livekit_control_sent=True,
        )
        duplicate = self.ledger.interrupt(
            session_id="session-1",
            turn_id="turn-1",
            correlation_id="corr-1",
            previous_generation=0,
            next_generation=1,
            reason="explicit_stop",
            provider_cancel_supported=True,
            provider_cancelled=True,
            delivered_audio_ms=120,
            browser_audio_stopped=True,
            livekit_control_sent=True,
        )

        self.assertEqual(first, duplicate)
        self.assertEqual(first["state"], "interrupted")
        self.assertEqual(first["generation"], 1)
        self.assertEqual(first["previous_generation"], 0)
        self.assertTrue(first["browser_audio_stopped"])
        self.assertTrue(first["livekit_control_sent"])
        self.assertEqual(self.ledger.counts()["interruptions"], 1)
        self.assertEqual(self.ledger.counts()["events"], 2)

    def test_append_only_triggers_reject_update_and_delete(self):
        self.claim()
        with sqlite3.connect(self.path) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "UPDATE browser_sense_turn_claims SET request_hash=? WHERE turn_id=?",
                    ("f" * 64, "turn-1"),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "DELETE FROM browser_sense_turn_events WHERE turn_id=?",
                    ("turn-1",),
                )

    def test_duplicate_interruption_merges_monotonic_browser_and_provider_evidence(self):
        self.claim()
        provider_first = self.ledger.interrupt(
            session_id="session-1",
            turn_id="turn-1",
            correlation_id="corr-1",
            previous_generation=0,
            next_generation=1,
            reason="explicit_stop",
            provider_cancel_supported=True,
            provider_cancelled=True,
            delivered_audio_ms=None,
            livekit_control_sent=True,
        )
        browser_confirmation = self.ledger.interrupt(
            session_id="session-1",
            turn_id="turn-1",
            correlation_id="corr-1",
            previous_generation=0,
            next_generation=1,
            reason="explicit_stop",
            provider_cancel_supported=False,
            provider_cancelled=False,
            delivered_audio_ms=None,
            browser_audio_stopped=True,
            livekit_control_sent=True,
        )

        self.assertNotEqual(provider_first["receipt_id"], browser_confirmation["receipt_id"])
        self.assertTrue(browser_confirmation["provider_cancelled"])
        self.assertTrue(browser_confirmation["browser_audio_stopped"])
        self.assertTrue(browser_confirmation["livekit_control_sent"])
        self.assertEqual(browser_confirmation["interruption_receipt_id"], provider_first["receipt_id"])

    def test_late_result_is_hash_only_and_changes_interrupted_disposition_to_discarded(self):
        self.claim()
        interruption = self.ledger.interrupt(
            session_id="session-1",
            turn_id="turn-1",
            correlation_id="corr-1",
            previous_generation=0,
            next_generation=1,
            reason="explicit_stop",
            provider_cancel_supported=False,
            provider_cancelled=False,
            delivered_audio_ms=None,
        )
        discarded = self.ledger.discard_late_result(
            session_id="session-1",
            turn_id="turn-1",
            correlation_id="corr-1",
            original_generation=0,
            response_hash="c" * 64,
        )

        self.assertEqual(discarded["state"], "interrupted")
        self.assertEqual(discarded["late_result_disposition"], "discarded")
        self.assertEqual(discarded["late_response_hash"], "c" * 64)
        self.assertNotIn("response", discarded)
        self.assertEqual(discarded["interruption_receipt_id"], interruption["receipt_id"])


if __name__ == "__main__":
    unittest.main()
