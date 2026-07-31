import json
from pathlib import Path

from aether.runtime.body import (
    ConformedRuntimeBody,
    FounderAcceptanceRequest,
    RuntimeBodyConfig,
    TtsAuditionRequest,
)
from aether.runtime.mcp import AetherMcpActivation, AetherMcpConfig


class FakeMind:
    def __init__(self, alive=True):
        self.alive = alive

    def is_alive(self):
        return self.alive

    def evaluate(self, **kwargs):
        return {
            "approved": True,
            "alignment_score": 0.95,
            "warnings": [],
            "escalate_to_dee": False,
        }


def make_body(tmp_path: Path) -> ConformedRuntimeBody:
    return ConformedRuntimeBody(
        RuntimeBodyConfig(aether_home=tmp_path, mind_url="http://127.0.0.1:8765"),
        mind_client=FakeMind(alive=True),
    )


def senses_evidence():
    return {
        "browser_senses_status": {
            "status": "ok",
            "gateway": {
                "public_routes": [
                    "/health",
                    "/api/browser-senses/status",
                    "/senses",
                    "/senses/app.js",
                ]
            },
        }
    }


def test_founder_acceptance_packet_starts_pending(tmp_path):
    body = make_body(tmp_path)

    packet = body.founder_acceptance_packet()
    statuses = {item["id"]: item["status"] for item in packet["criteria"]}

    assert packet["schema"] == "aether.founder-acceptance.v1"
    assert statuses["runtime_body_conformance"] == "pass"
    assert statuses["founder_attestation"] == "pending"
    assert statuses["aether_mcp_activation"] == "pending"
    assert packet["acceptance_state"]["founder_proven"] is False


def test_founder_acceptance_blocks_missing_required_evidence(tmp_path):
    body = make_body(tmp_path)

    result = body.accept_founder_packet(
        FounderAcceptanceRequest(
            founder_id="Dee",
            attestation="I accept this packet only when required evidence is complete.",
        )
    )

    assert result["accepted"] is False
    assert result["reason"] == "pending_required_evidence"
    assert "tts_fallback_proof" in result["pending_evidence"]
    assert "aionui_senses_public_health" in result["pending_evidence"]
    assert "aether_mcp_activation" in result["pending_evidence"]
    assert body.conformance()["founder_proven"] is False


def test_founder_acceptance_sets_founder_proven_after_signed_record(tmp_path):
    body = make_body(tmp_path)
    AetherMcpActivation(
        AetherMcpConfig(aether_home=tmp_path, mind_url="http://127.0.0.1:8765")
    ).activate()
    body.audition_tts(
        TtsAuditionRequest(
            text="Aether founder acceptance fallback proof.",
            allow_external=False,
        )
    )

    result = body.accept_founder_packet(
        FounderAcceptanceRequest(
            founder_id="Dee",
            attestation="I accept this Aether founder acceptance packet for the current local batch.",
            evidence=senses_evidence(),
        )
    )

    assert result["accepted"] is True
    assert result["decision"] == "accepted"
    assert result["founder_proven"] is True
    assert body.conformance()["founder_proven"] is True

    record = json.loads((tmp_path / "runtime" / "founder_acceptance" / "latest_acceptance.json").read_text())
    assert record["founder_id"] == "Dee"
    assert record["packet_id"] == result["packet_id"]

    receipts = (tmp_path / "runtime" / "body" / "receipts.jsonl").read_text(encoding="utf-8")
    assert "founder.acceptance.recorded" in receipts
