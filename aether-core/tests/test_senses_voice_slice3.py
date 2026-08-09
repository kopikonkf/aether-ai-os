from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
import yaml
from aether.voice.adapters import GeminiExactTextTTSAdapter, HttpResponse
from aether.voice.contracts import VoiceSynthesisRequest
from aether.voice.policy import BoundedVoicePromptCompiler, VoiceProfilePolicy
from aether.voice.runtime import (
    ExactTextVoiceRuntime,
    VoiceDeploymentManifest,
    VoiceTurnRequest,
)

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


def _policy() -> VoiceProfilePolicy:
    return VoiceProfilePolicy.from_persona(PERSONA_PATH)


def _deployment() -> VoiceDeploymentManifest:
    return VoiceDeploymentManifest.from_yaml(MANIFEST_PATH)


def test_persona_voice_policy_is_provider_neutral_and_hash_bound() -> None:
    policy = _policy()

    assert policy.default_preset == "warm_composed"
    assert policy.allowed_presets == (
        "neutral",
        "warm_composed",
        "technical_clear",
        "reassuring",
        "urgent_calm",
        "playful_light",
    )
    assert "approvals" in policy.forbidden_cue_contexts
    assert len(policy.voice_profile_sha256) == 64

    voice_profile = policy.public_dict()
    serialized = json.dumps(voice_profile, sort_keys=True).casefold()
    assert "gemini" not in serialized
    assert "billing" not in serialized
    assert "model" not in serialized
    assert "aoede" not in serialized


def test_bounded_compiler_is_deterministic_and_never_sends_full_persona() -> None:
    compiler = BoundedVoicePromptCompiler(_policy())
    speech_text = "Dee, deployment selesai. Totalnya Rp150.000 pada 7 Agustus 2026."

    first = compiler.compile(
        speech_text,
        delivery_preset_id="technical_clear",
        expressive_cue_id="gentle_emphasis",
    )
    second = compiler.compile(
        speech_text,
        delivery_preset_id="technical_clear",
        expressive_cue_id="gentle_emphasis",
    )

    assert first == second
    assert first.delivery_preset_id == "technical_clear"
    assert first.expressive_cue_id == "gentle_emphasis"
    assert first.speech_text_sha256 != first.director_prompt_sha256
    assert len(first.director_instruction) <= 1_200
    assert speech_text not in first.director_instruction
    assert "ACTION AND TOOL PROTOCOL" not in first.director_instruction
    assert "Aether must improve because she chooses to" not in first.director_instruction


def test_unknown_hints_default_and_precision_context_suppresses_cues() -> None:
    compiler = BoundedVoicePromptCompiler(_policy())
    compiled = compiler.compile(
        "Setujui transfer Rp150.000 sekarang.",
        delivery_preset_id="raw-provider-directive: shout",
        expressive_cue_id="brief_laugh",
        contexts={"approvals", "financial_amounts"},
    )

    assert compiled.delivery_preset_id == "warm_composed"
    assert compiled.expressive_cue_id is None
    assert compiled.precision_critical is True
    assert compiled.rejected_hints == (
        "delivery_preset:unsupported",
        "expressive_cue:suppressed_precision_critical",
    )
    assert "shout" not in compiled.director_instruction.casefold()
    assert "laugh" not in compiled.director_instruction.casefold()


def test_short_exact_text_is_not_rejected_when_its_character_appears_in_director() -> None:
    compiled = BoundedVoicePromptCompiler(_policy()).compile("A")
    request = VoiceSynthesisRequest(
        text="A",
        language="id-ID",
        correlation_id="short-turn",
        delivery_instruction=compiled.director_instruction,
    )

    assert request.exact_text_provider_input.endswith("\nA")


def test_gemini_adapter_sends_only_bounded_exact_text_payload() -> None:
    deployment = _deployment()
    compiler = BoundedVoicePromptCompiler(_policy())
    compiled = compiler.compile(
        "Halo, Dee. Aku Aether.",
        delivery_preset_id="warm_composed",
    )
    audio = b"deterministic-pcm-audio"
    transport = Transport(
        [
            HttpResponse(
                200,
                json.dumps(
                    {
                        "output_audio": {
                            "data": base64.b64encode(audio).decode(),
                            "mime_type": "audio/pcm;rate=24000",
                            "sample_rate": 24000,
                            "channels": 1,
                        }
                    }
                ).encode(),
                {"x-request-id": "gemini-request-1"},
            )
        ]
    )
    adapter = GeminiExactTextTTSAdapter(deployment.provider, transport)
    request = VoiceSynthesisRequest(
        text="Halo, Dee. Aku Aether.",
        language="id-ID",
        correlation_id="turn-gemini-1",
        delivery_instruction=compiled.director_instruction,
        delivery_preset_id=compiled.delivery_preset_id,
        voice_profile_sha256=compiled.voice_profile_sha256,
        compiler_sha256=compiled.compiler_sha256,
    )

    artifact = adapter.synthesize(request, lambda ref: "gemini-api-secret")

    assert artifact.audio == audio
    assert artifact.content_type == "audio/l16; rate=24000; channels=1"
    url, headers, body, content_type = transport.calls[0]
    payload = json.loads(body)
    assert url == "https://generativelanguage.googleapis.com/v1beta/interactions"
    assert headers == {"x-goog-api-key": "gemini-api-secret"}
    assert content_type == "application/json"
    assert set(payload) == {
        "generation_config",
        "input",
        "model",
        "response_format",
    }
    assert payload["model"] == "gemini-3.1-flash-tts-preview"
    assert payload["generation_config"] == {
        "speech_config": [{"voice": "Aoede"}]
    }
    assert payload["input"].count(request.text) == 1
    assert payload["input"].endswith(request.text)
    assert "gemini-api-secret" not in body.decode()
    assert "system_prompt" not in body.decode()
    assert "tool schemas" not in body.decode().casefold()


def test_gemini_adapter_parses_interactions_steps_audio_part() -> None:
    """The interactions endpoint returns audio as a steps[].content[] audio part."""
    deployment = _deployment()
    compiler = BoundedVoicePromptCompiler(_policy())
    compiled = compiler.compile(
        "Halo, Dee. Aku Aether.",
        delivery_preset_id="warm_composed",
    )
    audio = b"deterministic-steps-pcm-audio"
    transport = Transport(
        [
            HttpResponse(
                200,
                json.dumps(
                    {
                        "id": "v1_abc",
                        "status": "completed",
                        "steps": [
                            {
                                "type": "model_output",
                                "content": [
                                    {
                                        "type": "audio",
                                        "mime_type": "audio/l16",
                                        "mime_type_string": "audio/l16; rate=24000; channels=1",
                                        "data": base64.b64encode(audio).decode(),
                                        "channels": 1,
                                        "sample_rate": 24000,
                                    }
                                ],
                            }
                        ],
                        "object": "interaction",
                        "model": deployment.provider.model_id,
                    }
                ).encode(),
                {"x-request-id": "gemini-request-steps"},
            )
        ]
    )
    adapter = GeminiExactTextTTSAdapter(deployment.provider, transport)
    request = VoiceSynthesisRequest(
        text="Halo, Dee. Aku Aether.",
        language="id-ID",
        correlation_id="turn-gemini-steps",
        delivery_instruction=compiled.director_instruction,
        delivery_preset_id=compiled.delivery_preset_id,
        voice_profile_sha256=compiled.voice_profile_sha256,
        compiler_sha256=compiled.compiler_sha256,
    )

    artifact = adapter.synthesize(request, lambda ref: "gemini-api-secret")

    assert artifact.audio == audio
    assert artifact.content_type == "audio/l16; rate=24000; channels=1"
    assert artifact.extension == "pcm"


def test_gemini_adapter_rejects_pcm_params_outside_founder_alpha_contract() -> None:
    """Raw L16 PCM without the exact 24 kHz / mono contract is rejected."""
    deployment = _deployment()
    compiler = BoundedVoicePromptCompiler(_policy())
    compiled = compiler.compile(
        "Halo, Dee. Aku Aether.",
        delivery_preset_id="warm_composed",
    )
    audio = b"deterministic-pcm-audio"
    transport = Transport(
        [
            HttpResponse(
                200,
                json.dumps(
                    {
                        "status": "completed",
                        "steps": [
                            {
                                "type": "model_output",
                                "content": [
                                    {
                                        "type": "audio",
                                        "mime_type": "audio/l16",
                                        "mime_type_string": "audio/l16; rate=48000; channels=2",
                                        "data": base64.b64encode(audio).decode(),
                                        "channels": 2,
                                        "sample_rate": 48000,
                                    }
                                ],
                            }
                        ],
                    }
                ).encode(),
                {},
            )
        ]
    )
    adapter = GeminiExactTextTTSAdapter(deployment.provider, transport)
    request = VoiceSynthesisRequest(
        text="Halo, Dee. Aku Aether.",
        language="id-ID",
        correlation_id="turn-gemini-params",
        delivery_instruction=compiled.director_instruction,
    )

    try:
        adapter.synthesize(request, lambda ref: "gemini-api-secret")
    except ValueError as exc:
        assert "rate=24000 channels=1" in str(exc)
    else:
        raise AssertionError("out-of-contract PCM parameters must be rejected")


def test_founder_alpha_manifest_is_free_disclosed_and_cannot_auto_bill() -> None:
    deployment = _deployment()

    assert deployment.policy_id == "aether.voice.gemini-founder-alpha.v1"
    assert deployment.runtime_profile == "GOVERNED_PIPELINE"
    assert deployment.deployment_class == "FOUNDER_ALPHA_FREE"
    assert deployment.provider.model_id == "gemini-3.1-flash-tts-preview"
    assert deployment.provider.voice_id == "Aoede"
    assert deployment.provider.billing_tier == "free"
    assert deployment.provider.preview is True
    assert deployment.provider.audition_state == "pending_founder_audition"
    assert deployment.provider.credential_ref == "env://GEMINI_API_KEY"
    assert deployment.auto_upgrade_billing is False
    assert deployment.fallback_order == ("browser-speech", "text-only")
    assert deployment.private_text_only_supported is True
    assert "improve_provider_products" in deployment.provider.data_use_classification


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda value: value["provider"].update(
                {"credential_ref": "raw-secret-value"}
            ),
            "env:// reference",
        ),
        (
            lambda value: value.update(
                {"runtime_profile": "NATIVE_AUDIO_EXPERIMENTAL"}
            ),
            "GOVERNED_PIPELINE",
        ),
        (
            lambda value: value["billing"].update({"auto_upgrade": True}),
            "must not auto-upgrade",
        ),
        (
            lambda value: value["privacy"].update(
                {"founder_alpha_consent_required": False}
            ),
            "explicit Founder consent",
        ),
        (
            lambda value: value["evidence"].update(
                {"founder_audition_required": False}
            ),
            "require Founder audition",
        ),
        (
            lambda value: value["privacy"].update(
                {"founder_alpha_consent_required": "false"}
            ),
            "must be a boolean",
        ),
    ],
)
def test_manifest_rejects_raw_credentials_native_audio_and_auto_billing(
    tmp_path: Path, mutate, message: str
) -> None:
    value = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    mutate(value)
    path = tmp_path / "invalid-voice-manifest.yaml"
    path.write_text(yaml.safe_dump(value), encoding="utf-8")

    with pytest.raises((TypeError, ValueError), match=message):
        VoiceDeploymentManifest.from_yaml(path)


def test_private_consent_and_secret_boundaries_never_call_provider() -> None:
    deployment = _deployment()
    transport = Transport([])
    runtime = ExactTextVoiceRuntime(
        GeminiExactTextTTSAdapter(deployment.provider, transport),
        deployment=deployment,
        compiler=BoundedVoicePromptCompiler(_policy()),
        resolve_credential=lambda ref: "must-not-be-resolved",
        clock=Clock(),
    )

    private = runtime.synthesize(
        VoiceTurnRequest(
            speech_text="Percakapan privat Dee.",
            correlation_id="private-turn",
            founder_alpha_consent=True,
            private_text_only=True,
        )
    )
    no_consent = runtime.synthesize(
        VoiceTurnRequest(
            speech_text="Belum ada consent free tier.",
            correlation_id="no-consent-turn",
        )
    )
    secret = runtime.synthesize(
        VoiceTurnRequest(
            speech_text="API key: sk-test-secret-value",
            correlation_id="secret-turn",
            founder_alpha_consent=True,
        )
    )

    assert [value.receipt.outcome for value in (private, no_consent, secret)] == [
        "suppressed_private_text_only",
        "suppressed_consent_required",
        "suppressed_secret_class",
    ]
    assert [
        value.receipt.selected_fallback for value in (private, no_consent, secret)
    ] == ["text-only", "text-only", "text-only"]
    assert transport.calls == []
    public = json.dumps([value.receipt.public_dict() for value in (private, no_consent, secret)])
    assert "Percakapan privat" not in public
    assert "sk-test-secret-value" not in public
    assert "DIRECTOR" not in public


def test_runtime_consent_flags_must_be_real_booleans() -> None:
    with pytest.raises(TypeError, match="must be a boolean"):
        VoiceTurnRequest(
            speech_text="Teks yang tidak boleh lolos dengan consent truthy.",
            correlation_id="invalid-consent",
            founder_alpha_consent="yes",  # type: ignore[arg-type]
        )


def test_success_receipt_contains_hashes_and_no_text_or_director_prompt() -> None:
    deployment = _deployment()
    audio = b"runtime-audio"
    transport = Transport(
        [
            HttpResponse(
                200,
                json.dumps(
                    {"output_audio": {"data": base64.b64encode(audio).decode()}}
                ).encode(),
                {},
            )
        ]
    )
    runtime = ExactTextVoiceRuntime(
        GeminiExactTextTTSAdapter(deployment.provider, transport),
        deployment=deployment,
        compiler=BoundedVoicePromptCompiler(_policy()),
        resolve_credential=lambda ref: "test-only-key",
        clock=Clock(),
    )
    result = runtime.synthesize(
        VoiceTurnRequest(
            speech_text="Ini adalah exact authorized speech text.",
            correlation_id="success-turn",
            founder_alpha_consent=True,
            delivery_preset_id="reassuring",
        )
    )

    receipt = result.receipt.public_dict()
    assert result.artifact is not None
    assert receipt["outcome"] == "succeeded"
    assert receipt["runtime_profile"] == "GOVERNED_PIPELINE"
    assert receipt["billing_tier"] == "free"
    assert receipt["delivery_preset_id"] == "reassuring"
    assert len(receipt["speech_text_sha256"]) == 64
    assert len(receipt["voice_profile_sha256"]) == 64
    assert len(receipt["compiler_sha256"]) == 64
    assert len(receipt["director_prompt_sha256"]) == 64
    assert len(receipt["audio_sha256"]) == 64
    serialized = json.dumps(receipt)
    assert "exact authorized speech text" not in serialized
    assert "DIRECTOR" not in serialized
    assert "test-only-key" not in serialized


def test_quota_failure_opens_circuit_and_does_not_retry_storm() -> None:
    deployment = _deployment()
    transport = Transport(
        [
            HttpResponse(
                429,
                b'{"error":{"code":"RESOURCE_EXHAUSTED","message":"daily quota exceeded"}}',
                {"Retry-After": "60"},
            )
        ]
    )
    runtime = ExactTextVoiceRuntime(
        GeminiExactTextTTSAdapter(deployment.provider, transport),
        deployment=deployment,
        compiler=BoundedVoicePromptCompiler(_policy()),
        resolve_credential=lambda ref: "test-only-key",
        clock=Clock(),
    )
    request = VoiceTurnRequest(
        speech_text="Quota drill.",
        correlation_id="quota-turn",
        founder_alpha_consent=True,
    )

    failed = runtime.synthesize(request)
    short_circuited = runtime.synthesize(
        VoiceTurnRequest(
            speech_text="Second turn must not call Gemini.",
            correlation_id="quota-turn-2",
            founder_alpha_consent=True,
        )
    )

    assert failed.receipt.outcome == "fallback_required"
    assert failed.receipt.fallback_trigger_class == "quota_exhausted"
    assert failed.receipt.circuit_state == "open"
    assert failed.receipt.selected_fallback == "browser-speech"
    assert short_circuited.receipt.outcome == "circuit_open"
    assert short_circuited.receipt.selected_fallback == "browser-speech"
    assert len(transport.calls) == 1
