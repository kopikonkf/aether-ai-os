import json
from pathlib import Path

from aether.runtime.body import ConformedRuntimeBody, RuntimeBodyConfig
from aether.runtime.mvp20 import AetherMvp20Release


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


def release_conformance():
    return {
        "conformed": True,
        "mutable_state": "AETHER_HOME",
        "fail_safe_when_mind_down": True,
        "direct_mind_filesystem_writes": False,
        "tts_fallback_proof": True,
        "founder_proven": True,
        "mcp_required_tools_active": True,
    }


def release_evidence():
    return {
        "browser_senses_status": {
            "status": "ok",
            "gateway": {
                "public_routes": ["/health", "/api/browser-senses/status", "/senses"],
            },
        },
        "private_experiment": {"status": "validated"},
        "impact_brief": {"status": "written"},
        "approval": {"approved": True},
        "deployment_adapter": {"status": "ready"},
        "public_promotion": {"status": "published"},
        "analytics": {"status": "ready", "events": 5},
        "lead_ledger": {"status": "ready", "leads": 2},
        "demand": {"status": "verified", "signals": 4},
        "revenue_linkage": {"status": "verified", "linked": True},
        "rollback": {"status": "armed"},
        "kill_switch": {"status": "armed"},
        "portfolio_reallocation": {"status": "ready"},
        "strategy_learning": {"status": "ready", "lessons": ["local demand loop captured"]},
    }


def test_mvp20_packet_starts_pending_without_evidence(tmp_path):
    release = AetherMvp20Release(tmp_path)

    packet = release.build_packet(persist=True)

    assert packet["release_name"] == "MVP v0.20"
    assert packet["ready"] is False
    assert packet["state"] == "source-present"
    statuses = {item["id"]: item["status"] for item in packet["criteria"]}
    assert statuses["validated_private_experiment"] == "pending"
    assert statuses["rollback_and_kill_switch"] == "pending"
    assert (tmp_path / "runtime" / "releases" / "mvp_v0_20" / "latest_packet.json").exists()
    assert release.status()["packet_exists"] is True


def test_mvp20_packet_becomes_ready_with_release_evidence(tmp_path):
    release = AetherMvp20Release(tmp_path)

    packet = release.build_packet(
        runtime_health={"status": "ok"},
        runtime_conformance=release_conformance(),
        evidence=release_evidence(),
    )

    assert packet["ready"] is True
    assert packet["required_passed"] == packet["required_total"]
    assert release.status()["ready"] is True

    markdown = release.render_laststandingpoint(packet)
    assert "MVP v0.20" in markdown
    assert "Governed Shipping + Measured Demand Operations" in markdown
    assert "`validated_private_experiment`" in markdown


def test_body_mvp20_packet_records_receipt(tmp_path):
    body = make_body(tmp_path)

    health = body.health()
    conformance = body.conformance()
    packet = body.mvp20_packet({"private_experiment": {"status": "validated"}})

    assert health["mvp20"]["release_name"] == "MVP v0.20"
    assert conformance["mvp20_release"]["release_name"] == "MVP v0.20"
    assert packet["receipt_id"]
    assert packet["packet_id"]
    assert body.mvp20_status()["packet_exists"] is True

    receipts = (tmp_path / "runtime" / "body" / "receipts.jsonl").read_text(encoding="utf-8")
    assert "mvp20.packet.generated" in receipts

    latest_packet = json.loads(
        (tmp_path / "runtime" / "releases" / "mvp_v0_20" / "latest_packet.json").read_text(encoding="utf-8")
    )
    assert latest_packet["schema"] == "aether.mvp.v0.20.release.v1"
