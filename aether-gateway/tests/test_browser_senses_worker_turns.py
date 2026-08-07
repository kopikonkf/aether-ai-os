from __future__ import annotations

import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = (
    Path(__file__).parents[1]
    / "src"
    / "aether_gateway"
    / "browser_senses"
    / "worker.py"
)
try:
    import requests as _requests  # noqa: F401
except ModuleNotFoundError:
    requests_stub = types.ModuleType("requests")

    class RequestException(Exception):
        pass

    requests_stub.RequestException = RequestException
    requests_stub.post = lambda *args, **kwargs: (_ for _ in ()).throw(RequestException())
    sys.modules["requests"] = requests_stub
SPEC = importlib.util.spec_from_file_location("aether_gateway_browser_worker", MODULE_PATH)
assert SPEC and SPEC.loader
worker = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = worker
SPEC.loader.exec_module(worker)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class LiveKitWorkerTurnTests(unittest.TestCase):
    def test_generation_invalidates_late_result_exactly_once(self):
        turns = worker.LiveKitTurnCoordinator()
        original = turns.begin()
        first = turns.interrupt("explicit_stop")
        duplicate = turns.interrupt("explicit_stop")

        self.assertEqual(first, duplicate)
        self.assertIsNotNone(first)
        previous, interrupted = first
        self.assertEqual(previous, original)
        self.assertEqual(interrupted.generation, original.generation + 1)
        self.assertFalse(turns.accepts(original))

    def test_control_packet_is_bounded_and_rejects_text_or_generation_skips(self):
        valid = {
            "type": "interrupt",
            "turn_id": "turn-1",
            "correlation_id": "corr-1",
            "previous_generation": 0,
            "next_generation": 1,
            "reason": "explicit_stop",
        }
        encoded = json.dumps(valid).encode()
        self.assertEqual(
            worker.parse_turn_control(encoded, worker.TURN_CONTROL_TOPIC),
            valid,
        )
        self.assertIsNone(worker.parse_turn_control(
            json.dumps({**valid, "text": "must-not-cross"}).encode(),
            worker.TURN_CONTROL_TOPIC,
        ))
        self.assertIsNone(worker.parse_turn_control(
            json.dumps({**valid, "next_generation": 2}).encode(),
            worker.TURN_CONTROL_TOPIC,
        ))
        self.assertIsNone(worker.parse_turn_control(encoded, "other-topic"))

    def test_turn_state_packet_contains_only_bounded_identity_and_receipt_metadata(self):
        turn = worker.LiveKitTurnGeneration("turn-1", "corr-1")
        payload = worker.turn_state_payload(
            turn,
            "completed",
            receipt_id="turn-receipt-1",
        )

        self.assertEqual(payload["turn_id"], "turn-1")
        self.assertEqual(payload["receipt_id"], "turn-receipt-1")
        self.assertNotIn("text", payload)
        self.assertRaises(
            ValueError,
            worker.turn_state_payload,
            turn,
            "completed",
        )

    def test_gateway_client_binds_ids_and_reports_provider_cancel_without_text(self):
        config = worker.LiveKitWorkerConfig(
            gateway_url="https://gateway.invalid",
            worker_token="worker-token",
            agent_name="aether-sense",
            stt_model="stt",
            stt_language="id",
            tts_model="tts",
            tts_voice="voice",
            stt_fallback_models=(),
            tts_fallback_models=(),
            tts_fallback_voices=(),
            greeting="hello",
            turn_detector="multilingual",
        )
        client = worker.AetherGatewayVoiceClient(config)
        turn = worker.LiveKitTurnGeneration("turn-1", "corr-1")
        interrupted = worker.LiveKitTurnGeneration(
            "turn-1", "corr-1", generation=1, interrupted=True, reason="explicit_stop"
        )
        calls = []

        def post(url, **kwargs):
            calls.append((url, kwargs))
            return FakeResponse({"response": "Aether response"})

        with patch.object(worker.requests, "post", side_effect=post):
            client.respond(
                room_name="room-1",
                participant_identity="founder",
                text="hello",
                turn=turn,
            )
            client.interrupt(
                room_name="room-1",
                previous=turn,
                interrupted=interrupted,
                provider_cancel_supported=True,
                provider_cancelled=True,
                livekit_control_sent=True,
            )

        self.assertEqual(calls[0][1]["json"]["turn_id"], "turn-1")
        self.assertEqual(calls[0][1]["json"]["correlation_id"], "corr-1")
        self.assertNotIn("text", calls[1][1]["json"])
        self.assertTrue(calls[1][1]["json"]["provider_cancelled"])
        self.assertTrue(calls[1][1]["json"]["livekit_control_sent"])
        self.assertFalse(calls[1][1]["json"]["browser_audio_stopped"])


if __name__ == "__main__":
    unittest.main()
