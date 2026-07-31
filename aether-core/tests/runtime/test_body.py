import json
from pathlib import Path

from aether.runtime.body import BodyRunRequest, ConformedRuntimeBody, RuntimeBodyConfig, TtsAuditionRequest
from aether.runtime.mcp import AetherMcpActivation, AetherMcpConfig


class FakeMind:
    def __init__(self, alive=True, decision=None, evaluate_error=None):
        self.alive = alive
        self.decision = decision or {
            "approved": True,
            "alignment_score": 0.95,
            "warnings": [],
            "escalate_to_dee": False,
        }
        self.evaluate_error = evaluate_error
        self.evaluations = []

    def is_alive(self):
        return self.alive

    def evaluate(self, **kwargs):
        self.evaluations.append(kwargs)
        if self.evaluate_error is not None:
            raise self.evaluate_error
        return dict(self.decision)


def make_body(tmp_path: Path, mind: FakeMind, daily_cap_usd: float = 10.0) -> ConformedRuntimeBody:
    config = RuntimeBodyConfig(
        aether_home=tmp_path,
        mind_url="http://127.0.0.1:8765",
        daily_cap_usd=daily_cap_usd,
    )
    return ConformedRuntimeBody(config, mind_client=mind)


def test_config_uses_aether_home_env(tmp_path):
    config = RuntimeBodyConfig.from_env({"AETHER_HOME": str(tmp_path)})
    assert config.aether_home == tmp_path
    assert config.mind_url == "http://127.0.0.1:8765"


def test_health_enters_fail_safe_when_mind_down(tmp_path):
    body = make_body(tmp_path, FakeMind(alive=False))
    health = body.health()
    assert health["status"] == "fail_safe"
    assert health["mind_alive"] is False
    assert health["authority"] == "subordinate_to_aether_mind"
    assert health["mvp20"]["release_name"] == "MVP v0.20"


def test_run_refuses_and_receipts_when_mind_down(tmp_path):
    body = make_body(tmp_path, FakeMind(alive=False))
    result = body.run(BodyRunRequest(goal="change identity"))
    assert result["accepted"] is False
    assert result["reason"] == "mind_unreachable_fail_safe"

    receipts = (tmp_path / "runtime" / "body" / "receipts.jsonl").read_text(encoding="utf-8")
    assert "body.run.refused" in receipts
    assert "mind_unreachable_fail_safe" in receipts


def test_run_records_budget_under_aether_home(tmp_path):
    mind = FakeMind(alive=True)
    body = make_body(tmp_path, mind)
    result = body.run(BodyRunRequest(goal="buy test API credit", max_amount_usd=2.5))

    assert result["accepted"] is True
    assert mind.evaluations

    state = json.loads((tmp_path / "runtime" / "body" / "budget_state.json").read_text(encoding="utf-8"))
    assert state["spent_today_usd"] == 2.5
    assert state["remaining_usd"] == 7.5


def test_run_blocks_over_budget_before_gate(tmp_path):
    mind = FakeMind(alive=True)
    body = make_body(tmp_path, mind, daily_cap_usd=1.0)
    result = body.run(BodyRunRequest(goal="overspend", max_amount_usd=2.0))

    assert result["accepted"] is False
    assert result["reason"] == "budget_cap_exceeded"
    assert mind.evaluations == []


def test_run_refuses_when_north_star_gate_errors(tmp_path):
    mind = FakeMind(alive=True, evaluate_error=RuntimeError("gate offline"))
    body = make_body(tmp_path, mind)
    result = body.run(BodyRunRequest(goal="irreversible", irreversible=True))

    assert result["accepted"] is False
    assert result["status"] == "fail_safe"
    assert result["reason"] == "north_star_unreachable_fail_safe"


def test_conformance_marks_unproven_live_wiring(tmp_path):
    body = make_body(tmp_path, FakeMind(alive=True))
    conformance = body.conformance()

    assert conformance["conformed"] is True
    assert conformance["mutable_state"] == "AETHER_HOME"
    assert conformance["live_provider_wired"] is False
    assert conformance["voice_wired"] is False
    assert conformance["google_tts_audition"] == "source_present"
    assert conformance["tts_fallback_proof"] is True
    assert conformance["mcp_activation"] == "source_present"
    assert conformance["mcp_required_tools_active"] is False
    assert conformance["founder_proven"] is False
    assert conformance["mvp20_release"]["release_name"] == "MVP v0.20"


def test_mcp_status_reflects_activation_record(tmp_path):
    body = make_body(tmp_path, FakeMind(alive=True))
    AetherMcpActivation(
        AetherMcpConfig(aether_home=tmp_path, mind_url="http://127.0.0.1:8765")
    ).activate()

    status = body.mcp_status()

    assert status["activated"] is True
    assert status["required_tools_active"] is True


def test_tts_audition_writes_local_fallback_proof(tmp_path):
    body = make_body(tmp_path, FakeMind(alive=True))
    result = body.audition_tts(
        TtsAuditionRequest(
            text="Aether online. Google TTS fallback proof.",
            allow_external=False,
        )
    )

    assert result["accepted"] is True
    assert result["provider"] == "local-wav-fallback"
    assert result["fallback_used"] is True

    audio = Path(result["audio_path"])
    metadata = Path(result["metadata_path"])
    assert audio.exists()
    assert metadata.exists()
    assert audio.read_bytes().startswith(b"RIFF")

    receipts = (tmp_path / "runtime" / "body" / "receipts.jsonl").read_text(encoding="utf-8")
    assert "tts.audition.completed" in receipts
    assert "local-wav-fallback" in receipts


def test_tts_external_audition_refuses_when_mind_down(tmp_path):
    body = make_body(tmp_path, FakeMind(alive=False))
    result = body.audition_tts(
        TtsAuditionRequest(
            text="This should not call an external voice provider.",
            allow_external=True,
        )
    )

    assert result["accepted"] is False
    assert result["status"] == "fail_safe"
    assert result["reason"] == "mind_unreachable_fail_safe"
