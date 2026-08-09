from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from aether.voice.adapters import HttpResponse
from aether.voice.contracts import VoiceSynthesisRequest
from aether.voice.runtime import ExactTextVoiceRuntime
from aether.voice.worker import CredentialedVoiceWorker

CORE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CORE_ROOT.parent
PERSONA_PATH = CORE_ROOT / "configs" / "persona.yaml"
MANIFEST_PATH = REPO_ROOT / "configs" / "runtime" / "gemini_tts_founder_alpha.yaml"


class Clock:
    def __init__(self) -> None:
        self.value = 1_000.0

    def __call__(self) -> float:
        value = self.value
        self.value += 0.025
        return value


class Transport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, str], bytes, str]] = []

    def post(self, url, *, headers, body, content_type):
        self.calls.append((url, dict(headers), body, content_type))
        return self.responses.pop(0)


def _ok_audio(audio: bytes = b"credentialed-pcm-audio") -> bytes:
    return json.dumps(
        {
            "output_audio": {
                "data": base64.b64encode(audio).decode(),
                "mime_type": "audio/pcm;rate=24000",
                "sample_rate": 24000,
                "channels": 1,
            }
        }
    ).encode()


def _worker(
    tmp_path: Path,
    responses: list[HttpResponse],
    *,
    loader=None,
    output_root: Path | None = None,
) -> CredentialedVoiceWorker:
    return CredentialedVoiceWorker(
        manifest_path=MANIFEST_PATH,
        persona_path=PERSONA_PATH,
        transport=Transport(responses),
        credential_loader=loader or (lambda ref: "env-resolved-key"),
        output_root=output_root or (tmp_path / "out"),
        clock=Clock(),
    )


def test_worker_readiness_is_non_activation_and_never_resolves_credential(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("AETHER_VOICE_WORKER_EXECUTE", raising=False)
    worker = _worker(tmp_path, [])
    readiness = worker.readiness()

    assert readiness["worker"] == "aether.voice.credentialed.v1"
    assert readiness["deployment_class"] == "FOUNDER_ALPHA_FREE"
    assert readiness["runtime_profile"] == "GOVERNED_PIPELINE"
    assert readiness["provider_id"] == "gemini-exact-tts"
    assert readiness["model_id"] == "gemini-3.1-flash-tts-preview"
    assert readiness["billing_tier"] == "free"
    assert readiness["livekit_worker_wired"] is False
    assert readiness["activate_gate"] is False
    assert readiness["credential_resolved"] is False
    assert readiness["credential_reference"] == "env://GEMINI_API_KEY"


def test_worker_refuses_raw_credential_reference() -> None:
    worker = CredentialedVoiceWorker(
        manifest_path=MANIFEST_PATH,
        persona_path=PERSONA_PATH,
        transport=Transport([]),
        output_root=Path("unused"),
    )
    try:
        worker._env_credential("sk-raw-secret-value")
    except ValueError as exc:
        assert "env://" in str(exc)
    else:
        raise AssertionError("raw credential must be refused")


def test_worker_credential_missing_raises(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    try:
        CredentialedVoiceWorker._env_credential("env://GEMINI_API_KEY")
    except RuntimeError as exc:
        assert "not configured" in str(exc)
    else:
        raise AssertionError("missing env credential must raise")


def test_worker_success_resolves_credential_and_proves_hash_only(tmp_path: Path) -> None:
    worker = _worker(
        tmp_path,
        [HttpResponse(200, _ok_audio(), {"x-request-id": "worker-1"})],
    )
    outcome = worker.run(
        "Ini adalah exact speech text untuk pekerja kredensial.",
        correlation_id="cred-worker-1",
        founder_alpha_consent=True,
    )

    assert outcome.request_accepted is True
    assert outcome.outcome == "succeeded"
    assert outcome.fallback_trigger_class == ""
    assert outcome.selected_fallback == ""
    assert outcome.provider_id == "gemini-exact-tts"
    assert outcome.model_id == "gemini-3.1-flash-tts-preview"
    assert len(outcome.receipt_id) == 64
    assert len(outcome.speech_text_sha256) == 64
    assert len(outcome.audio_sha256) == 64
    assert outcome.artifact_path is not None
    assert Path(outcome.artifact_path).read_bytes() == b"credentialed-pcm-audio"
    # The env-resolved key must be sent to the provider but never serialized.
    _, headers, body, _ = worker.transport.calls[0]
    assert headers["x-goog-api-key"] == "env-resolved-key"
    assert b"env-resolved-key" not in body
    # The speech text is present exactly once as the recitation transcript.
    assert body.count(b"pekerja kredensial") == 1


def test_worker_quota_failure_proves_fallback_without_retry_storm(tmp_path: Path) -> None:
    worker = _worker(
        tmp_path,
        [
            HttpResponse(
                429,
                b'{"error":{"code":"RESOURCE_EXHAUSTED","message":"daily quota"}}',
                {},
            )
        ],
    )
    outcome = worker.run(
        "Quota drill untuk pekerja.",
        correlation_id="cred-worker-2",
        founder_alpha_consent=True,
    )

    assert outcome.request_accepted is False
    assert outcome.outcome == "fallback_required"
    assert outcome.fallback_trigger_class == "quota_exhausted"
    assert outcome.selected_fallback == "browser-speech"
    assert outcome.artifact_path is None
    assert len(worker.transport.calls) == 1


def test_fallback_is_client_directive_not_server_side_synthesis(tmp_path: Path) -> None:
    worker = _worker(
        tmp_path,
        [
            HttpResponse(
                429,
                b'{"error":{"code":"RESOURCE_EXHAUSTED","message":"daily quota"}}',
                {},
            )
        ],
    )
    outcome = worker.run(
        "Fallback directive drill.",
        correlation_id="cred-worker-5",
        founder_alpha_consent=True,
    )

    # browser-speech is a directive: the worker never fabricates server-side audio.
    assert outcome.selected_fallback == "browser-speech"
    assert outcome.artifact_path is None
    assert outcome.audio_sha256 == ""
    assert len(worker.transport.calls) == 1


def test_worker_consent_gate_suppresses_without_provider_call(tmp_path: Path) -> None:
    worker = _worker(tmp_path, [])
    outcome = worker.run(
        "Belum ada consent Founder.",
        correlation_id="cred-worker-3",
        founder_alpha_consent=False,
    )

    assert outcome.request_accepted is False
    assert outcome.outcome == "suppressed_consent_required"
    assert outcome.selected_fallback == "text-only"
    assert worker.transport.calls == []


def test_worker_secret_suppression_never_calls_provider(tmp_path: Path) -> None:
    worker = _worker(tmp_path, [])
    outcome = worker.run(
        "API key: sk-test-secret-value",
        correlation_id="cred-worker-4",
        founder_alpha_consent=True,
    )

    assert outcome.outcome == "suppressed_secret_class"
    assert outcome.selected_fallback == "text-only"
    assert worker.transport.calls == []
    assert outcome.audio_sha256 == ""


def test_cli_dry_run_never_calls_provider(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.delenv("AETHER_VOICE_WORKER_EXECUTE", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-key")
    from aether.voice.worker import main

    code = main([
        "--text", "Halo",
        "--correlation", "cli-dry",
        "--manifest", str(MANIFEST_PATH),
        "--persona", str(PERSONA_PATH),
        "--dry-run",
    ])
    captured = capsys.readouterr().out
    payload = json.loads(captured)
    assert code == 0
    assert payload["status"] == "dry-run"
    assert payload["execute_allowed"] is False


def test_worker_artifact_path_cannot_escape_output_root(tmp_path: Path) -> None:
    """correlation_id must never introduce a path traversal into the artifact path."""
    worker = _worker(
        tmp_path,
        [HttpResponse(200, _ok_audio(), {})],
        output_root=tmp_path / "out",
    )
    outcome = worker.run(
        "Path traversal drill.",
        correlation_id="../../escape",
        founder_alpha_consent=True,
    )

    assert outcome.artifact_path is not None
    artifact = Path(outcome.artifact_path)
    assert artifact.parent.resolve() == (tmp_path / "out").resolve()
    assert (tmp_path / "escape.mp3").exists() is False
    assert artifact.exists() is True

