"""Governed exact-text TTS runtime for the Founder Alpha voice path."""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from aether.resilience import (
    CircuitBreaker,
    ProviderErrorSignal,
    classify_provider_error,
)

from .contracts import (
    CredentialResolver,
    VoiceArtifact,
    VoiceProvider,
    VoiceProviderManifest,
    VoiceSynthesisRequest,
    canonical_hash,
    sha256_bytes,
)
from .policy import BoundedVoicePromptCompiler, CompiledVoicePrompt

_SECRET_PATTERNS = (
    re.compile(
        r"(?i)\b(?:api[_ -]?key|access[_ -]?token|password|secret|credential)"
        r"\s*[:=]\s*\S{6,}"
    ),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{20,}\b"),
)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping")
    return value


def _text(value: object, label: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(f"{label} must not be empty")
    return result


def _tuple(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a non-empty list")
    result = tuple(_text(item, label) for item in value)
    if len(set(result)) != len(result):
        raise ValueError(f"{label} must not contain duplicates")
    return result


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{label} must be a boolean")
    return value


@dataclass(frozen=True)
class VoiceDeploymentManifest:
    policy_id: str
    runtime_profile: str
    deployment_class: str
    provider_endpoint: str
    provider: VoiceProviderManifest
    fallback_order: tuple[str, ...]
    founder_alpha_consent_required: bool
    private_text_only_supported: bool
    secret_classes_denied: tuple[str, ...]
    failure_threshold: int
    cooldown_seconds: float
    auto_upgrade_billing: bool
    paid_upgrade_requires_founder_authorization: bool
    exact_text_required: bool
    founder_audition_required: bool
    provider_terms_url: str
    pricing_url: str
    speech_generation_url: str

    @classmethod
    def from_yaml(cls, path: Path) -> VoiceDeploymentManifest:
        root = _mapping(
            yaml.safe_load(path.read_text(encoding="utf-8")) or {},
            "voice deployment manifest",
        )
        provider = _mapping(root.get("provider"), "voice deployment provider")
        privacy = _mapping(root.get("privacy"), "voice deployment privacy")
        circuit = _mapping(root.get("circuit"), "voice deployment circuit")
        billing = _mapping(root.get("billing"), "voice deployment billing")
        evidence = _mapping(root.get("evidence"), "voice deployment evidence")
        deployment_class = _text(
            root.get("deployment_class"), "voice deployment class"
        )
        runtime_profile = _text(root.get("runtime_profile"), "voice runtime profile")
        billing_tier = _text(provider.get("billing_tier"), "voice billing tier")
        credential_ref = _text(
            provider.get("credential_ref"), "voice credential reference"
        )
        if deployment_class != "FOUNDER_ALPHA_FREE":
            raise ValueError("slice 3 accepts only FOUNDER_ALPHA_FREE")
        if runtime_profile != "GOVERNED_PIPELINE":
            raise ValueError("v1 exact-text TTS requires GOVERNED_PIPELINE")
        if billing_tier != "free":
            raise ValueError("FOUNDER_ALPHA_FREE must use a free billing tier")
        if not credential_ref.startswith("env://"):
            raise ValueError("voice credential must be an env:// reference")
        auto_upgrade_billing = _boolean(
            billing.get("auto_upgrade"), "voice automatic billing upgrade"
        )
        if auto_upgrade_billing:
            raise ValueError("voice deployment must not auto-upgrade billing")
        endpoint = _text(provider.get("endpoint"), "voice provider endpoint")
        if not endpoint.startswith("https://"):
            raise ValueError("voice provider endpoint must use HTTPS")
        fallback_order = _tuple(root.get("fallback_order"), "voice fallback order")
        consent_required = _boolean(
            privacy.get("founder_alpha_consent_required"),
            "voice Founder Alpha consent requirement",
        )
        private_text_only_supported = _boolean(
            privacy.get("private_text_only_supported"),
            "voice Private text-only support",
        )
        paid_upgrade_requires_authorization = _boolean(
            billing.get("paid_upgrade_requires_founder_authorization"),
            "voice paid-upgrade authorization requirement",
        )
        exact_text_required = _boolean(
            evidence.get("exact_text_required"), "voice exact-text requirement"
        )
        founder_audition_required = _boolean(
            evidence.get("founder_audition_required"),
            "voice Founder audition requirement",
        )
        if not consent_required:
            raise ValueError("FOUNDER_ALPHA_FREE requires explicit Founder consent")
        if not private_text_only_supported or "text-only" not in fallback_order:
            raise ValueError("voice deployment must preserve a text-only privacy path")
        if not paid_upgrade_requires_authorization:
            raise ValueError("paid voice upgrade requires Founder authorization")
        if not exact_text_required:
            raise ValueError("voice deployment must require exact text")
        if not founder_audition_required:
            raise ValueError("voice deployment must require Founder audition")
        manifest = VoiceProviderManifest(
            provider_id=_text(provider.get("provider_id"), "voice provider ID"),
            model_id=_text(provider.get("model_id"), "voice model ID"),
            voice_id=_text(provider.get("voice_id"), "voice ID"),
            language=_text(provider.get("language"), "voice language"),
            output_format=_text(provider.get("output_format"), "voice output format"),
            credential_ref=credential_ref,
            priority=int(provider.get("priority") or 1),
            capabilities=frozenset({"voice.tts", "voice.tts.exact-text"}),
            streaming=_boolean(provider.get("streaming"), "voice streaming support"),
            data_policy_tags=frozenset(
                {"hosted", "free-tier", "provider-training-permitted"}
            ),
            cost_class="free",
            billing_tier=billing_tier,
            quota_class=_text(provider.get("quota_class"), "voice quota class"),
            data_use_classification=_text(
                provider.get("data_use_classification"),
                "voice data-use classification",
            ),
            preview=_boolean(provider.get("preview"), "voice preview state"),
            terms_snapshot_date=_text(
                provider.get("terms_snapshot_date"),
                "voice terms snapshot date",
            ),
            audition_state=_text(
                provider.get("audition_state"), "voice audition state"
            ),
        )
        return cls(
            policy_id=_text(root.get("policy_id"), "voice policy ID"),
            runtime_profile=runtime_profile,
            deployment_class=deployment_class,
            provider_endpoint=endpoint,
            provider=manifest,
            fallback_order=fallback_order,
            founder_alpha_consent_required=consent_required,
            private_text_only_supported=private_text_only_supported,
            secret_classes_denied=_tuple(
                privacy.get("secret_classes_denied"),
                "voice denied secret classes",
            ),
            failure_threshold=int(circuit.get("failure_threshold") or 1),
            cooldown_seconds=float(circuit.get("cooldown_seconds") or 60),
            auto_upgrade_billing=auto_upgrade_billing,
            paid_upgrade_requires_founder_authorization=(
                paid_upgrade_requires_authorization
            ),
            exact_text_required=exact_text_required,
            founder_audition_required=founder_audition_required,
            provider_terms_url=_text(
                evidence.get("provider_terms_url"), "voice provider terms URL"
            ),
            pricing_url=_text(evidence.get("pricing_url"), "voice pricing URL"),
            speech_generation_url=_text(
                evidence.get("speech_generation_url"),
                "voice speech-generation URL",
            ),
        )


@dataclass(frozen=True)
class VoiceTurnRequest:
    speech_text: str
    correlation_id: str
    founder_alpha_consent: bool = False
    private_text_only: bool = False
    delivery_preset_id: str | None = None
    expressive_cue_id: str | None = None
    contexts: frozenset[str] = frozenset()
    data_classifications: frozenset[str] = frozenset()
    pronunciation_lexicon_version: str = "none"

    def __post_init__(self) -> None:
        if not isinstance(self.founder_alpha_consent, bool):
            raise TypeError("founder_alpha_consent must be a boolean")
        if not isinstance(self.private_text_only, bool):
            raise TypeError("private_text_only must be a boolean")


@dataclass(frozen=True)
class VoiceTurnReceipt:
    schema: str
    outcome: str
    correlation_id: str
    runtime_profile: str
    provider_id: str
    model_id: str
    voice_id: str
    billing_tier: str
    deployment_class: str
    terms_snapshot_date: str
    speech_text_sha256: str
    voice_profile_sha256: str
    compiler_sha256: str
    director_prompt_sha256: str
    delivery_preset_id: str
    expressive_cue_id: str | None
    pronunciation_lexicon_version: str
    request_accepted: bool
    first_audio_latency_ms: float
    total_latency_ms: float
    audio_sha256: str
    fallback_trigger_class: str
    circuit_state: str
    selected_fallback: str
    rejected_hints: tuple[str, ...]
    data_classifications: tuple[str, ...]
    receipt_id: str

    @classmethod
    def build(cls, **values: object) -> VoiceTurnReceipt:
        payload = {"schema": "aether.voice-turn-receipt.v1", **values}
        receipt_id = canonical_hash(payload)
        return cls(**payload, receipt_id=receipt_id)

    def public_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class VoiceRuntimeResult:
    artifact: VoiceArtifact | None
    receipt: VoiceTurnReceipt


class ExactTextVoiceRuntime:
    """Apply consent/privacy policy, compile delivery, synthesize once, and receipt."""

    def __init__(
        self,
        provider: VoiceProvider,
        *,
        deployment: VoiceDeploymentManifest,
        compiler: BoundedVoicePromptCompiler,
        resolve_credential: CredentialResolver,
        clock: Callable[[], float],
    ) -> None:
        if provider.manifest.provider_id != deployment.provider.provider_id:
            raise ValueError("voice provider does not match deployment manifest")
        provider_endpoint = str(getattr(provider, "endpoint", deployment.provider_endpoint))
        if provider_endpoint != deployment.provider_endpoint:
            raise ValueError("voice provider endpoint does not match deployment manifest")
        self.provider = provider
        self.deployment = deployment
        self.compiler = compiler
        self.resolve_credential = resolve_credential
        self.clock = clock
        self.circuit = CircuitBreaker(
            failure_threshold=deployment.failure_threshold,
            cooldown_seconds=deployment.cooldown_seconds,
        )

    def synthesize(self, turn: VoiceTurnRequest) -> VoiceRuntimeResult:
        speech_text = str(turn.speech_text or "")
        if not speech_text.strip():
            raise ValueError("speech_text must not be empty")
        started = self.clock()
        if turn.private_text_only:
            if not self.deployment.private_text_only_supported:
                raise ValueError("deployment does not support Private text-only")
            return self._without_provider(
                turn,
                outcome="suppressed_private_text_only",
                trigger="private_text_only",
                observed_at=started,
            )
        if (
            self.deployment.founder_alpha_consent_required
            and not turn.founder_alpha_consent
        ):
            return self._without_provider(
                turn,
                outcome="suppressed_consent_required",
                trigger="consent_required",
                observed_at=started,
            )
        if self._contains_secret(speech_text, turn.data_classifications):
            return self._without_provider(
                turn,
                outcome="suppressed_secret_class",
                trigger="secret_class",
                observed_at=started,
            )
        if not self.circuit.allow_request(now=started):
            return self._without_provider(
                turn,
                outcome="circuit_open",
                trigger="circuit_open",
                observed_at=started,
            )

        compiled = self.compiler.compile(
            speech_text,
            delivery_preset_id=turn.delivery_preset_id,
            expressive_cue_id=turn.expressive_cue_id,
            contexts=turn.contexts,
        )
        request = VoiceSynthesisRequest(
            text=speech_text,
            language=self.deployment.provider.language,
            correlation_id=turn.correlation_id,
            delivery_instruction=compiled.director_instruction,
            delivery_preset_id=compiled.delivery_preset_id,
            expressive_cue_id=compiled.expressive_cue_id,
            voice_profile_sha256=compiled.voice_profile_sha256,
            compiler_sha256=compiled.compiler_sha256,
            pronunciation_lexicon_version=turn.pronunciation_lexicon_version,
            precision_critical=compiled.precision_critical,
        )
        try:
            artifact = self.provider.synthesize(request, self.resolve_credential)
        except Exception as error:  # noqa: BLE001 - providers expose vendor errors
            completed = self.clock()
            kind = classify_provider_error(self._error_signal(error))
            self.circuit.record_failure(kind, now=completed)
            return VoiceRuntimeResult(
                artifact=None,
                receipt=self._receipt(
                    turn,
                    compiled=compiled,
                    synthesis_request=request,
                    outcome="fallback_required",
                    trigger=kind.value,
                    request_accepted=False,
                    started_at=started,
                    completed_at=completed,
                ),
            )
        completed = self.clock()
        self.circuit.record_success()
        return VoiceRuntimeResult(
            artifact=artifact,
            receipt=self._receipt(
                turn,
                compiled=compiled,
                synthesis_request=request,
                artifact=artifact,
                outcome="succeeded",
                trigger="",
                request_accepted=True,
                started_at=started,
                completed_at=completed,
            ),
        )

    def _without_provider(
        self,
        turn: VoiceTurnRequest,
        *,
        outcome: str,
        trigger: str,
        observed_at: float,
    ) -> VoiceRuntimeResult:
        return VoiceRuntimeResult(
            artifact=None,
            receipt=self._receipt(
                turn,
                compiled=None,
                synthesis_request=None,
                outcome=outcome,
                trigger=trigger,
                request_accepted=False,
                started_at=observed_at,
                completed_at=observed_at,
            ),
        )

    def _receipt(
        self,
        turn: VoiceTurnRequest,
        *,
        compiled: CompiledVoicePrompt | None,
        synthesis_request: VoiceSynthesisRequest | None,
        outcome: str,
        trigger: str,
        request_accepted: bool,
        started_at: float,
        completed_at: float,
        artifact: VoiceArtifact | None = None,
    ) -> VoiceTurnReceipt:
        latency_ms = round(max(0.0, completed_at - started_at) * 1000, 3)
        privacy_suppression = {
            "suppressed_private_text_only",
            "suppressed_consent_required",
            "suppressed_secret_class",
        }
        if outcome in privacy_suppression:
            selected_fallback = "text-only"
        elif outcome == "succeeded":
            selected_fallback = ""
        else:
            selected_fallback = self.deployment.fallback_order[0]
        prompt_hash = (
            sha256_bytes(synthesis_request.exact_text_provider_input.encode("utf-8"))
            if synthesis_request is not None
            else ""
        )
        return VoiceTurnReceipt.build(
            outcome=outcome,
            correlation_id=turn.correlation_id,
            runtime_profile=self.deployment.runtime_profile,
            provider_id=self.deployment.provider.provider_id,
            model_id=self.deployment.provider.model_id,
            voice_id=self.deployment.provider.voice_id,
            billing_tier=self.deployment.provider.billing_tier,
            deployment_class=self.deployment.deployment_class,
            terms_snapshot_date=self.deployment.provider.terms_snapshot_date,
            speech_text_sha256=sha256_bytes(turn.speech_text.encode("utf-8")),
            voice_profile_sha256=self.compiler.policy.voice_profile_sha256,
            compiler_sha256=self.compiler.compiler_sha256,
            director_prompt_sha256=prompt_hash,
            delivery_preset_id=(
                compiled.delivery_preset_id
                if compiled is not None
                else self.compiler.policy.default_preset
            ),
            expressive_cue_id=(
                compiled.expressive_cue_id if compiled is not None else None
            ),
            pronunciation_lexicon_version=turn.pronunciation_lexicon_version,
            request_accepted=request_accepted,
            first_audio_latency_ms=latency_ms if artifact is not None else 0.0,
            total_latency_ms=latency_ms,
            audio_sha256=(
                sha256_bytes(artifact.audio) if artifact is not None else ""
            ),
            fallback_trigger_class=trigger,
            circuit_state=self.circuit.state.value,
            selected_fallback=selected_fallback,
            rejected_hints=(compiled.rejected_hints if compiled is not None else ()),
            data_classifications=tuple(
                sorted(
                    set(turn.data_classifications).intersection(
                        self.deployment.secret_classes_denied
                    )
                )
            ),
        )

    def _contains_secret(
        self, speech_text: str, data_classifications: Iterable[str]
    ) -> bool:
        if set(data_classifications).intersection(
            self.deployment.secret_classes_denied
        ):
            return True
        return any(pattern.search(speech_text) for pattern in _SECRET_PATTERNS)

    @staticmethod
    def _error_signal(error: Exception) -> ProviderErrorSignal:
        return ProviderErrorSignal(
            status_code=getattr(error, "status_code", None),
            error_code=str(getattr(error, "error_code", "")),
            message=str(error),
            retry_after_seconds=getattr(error, "retry_after_seconds", None),
            exception_name=type(error).__name__,
        )
