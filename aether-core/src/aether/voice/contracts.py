"""Credential-free contracts for voice synthesis, transcription, and audition."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Protocol, runtime_checkable


CredentialResolver = Callable[[str], str]


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_hash(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(encoded)


@dataclass(frozen=True)
class VoiceProviderManifest:
    provider_id: str
    model_id: str
    voice_id: str
    language: str
    output_format: str
    credential_ref: str
    priority: int
    capabilities: frozenset[str] = frozenset({"voice.tts"})
    streaming: bool = False
    data_policy_tags: frozenset[str] = frozenset({"hosted"})
    cost_class: str = "metered"
    billing_tier: str = "unspecified"
    quota_class: str = "unspecified"
    data_use_classification: str = "unspecified"
    preview: bool = False
    terms_snapshot_date: str = ""
    audition_state: str = "unreviewed"

    def public_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["capabilities"] = sorted(self.capabilities)
        value["data_policy_tags"] = sorted(self.data_policy_tags)
        return value


@dataclass(frozen=True)
class VoiceSynthesisRequest:
    text: str
    language: str
    correlation_id: str
    speaking_rate: float = 1.0
    pitch: float = 0.0
    delivery_instruction: str = ""
    delivery_preset_id: str = "neutral"
    expressive_cue_id: str | None = None
    voice_profile_sha256: str = ""
    compiler_sha256: str = ""
    pronunciation_lexicon_version: str = "none"
    precision_critical: bool = False

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("voice synthesis text must not be empty")
        if "\x00" in self.text:
            raise ValueError("voice synthesis text must not contain NUL")
        if len(self.delivery_instruction) > 1_200:
            raise ValueError("voice delivery instruction exceeds the 1200-character bound")

    @property
    def input_sha256(self) -> str:
        return sha256_bytes(self.text.encode("utf-8"))

    @property
    def delivery_instruction_sha256(self) -> str:
        return sha256_bytes(self.delivery_instruction.encode("utf-8"))

    @property
    def exact_text_provider_input(self) -> str:
        if not self.delivery_instruction:
            return self.text
        return (
            f"{self.delivery_instruction}\n\n"
            "TRANSCRIPT — RECITE VERBATIM\n"
            f"{self.text}"
        )


@dataclass(frozen=True)
class VoiceArtifact:
    audio: bytes
    content_type: str
    extension: str


@dataclass(frozen=True)
class VoiceSynthesisReceipt:
    schema: str
    provider_id: str
    model_id: str
    voice_id: str
    correlation_id: str
    input_sha256: str
    audio_sha256: str
    byte_length: int
    content_type: str
    output_format: str
    started_at: float
    first_audio_latency_ms: float
    total_latency_ms: float
    attempt_count: int
    fallback_from: tuple[str, ...] = ()
    error_classifications: tuple[str, ...] = ()
    receipt_id: str = ""

    @classmethod
    def build(cls, **values: object) -> "VoiceSynthesisReceipt":
        payload = {"schema": "aether.voice-synthesis-receipt.v1", **values}
        payload["fallback_from"] = list(payload.get("fallback_from", ()))
        payload["error_classifications"] = list(payload.get("error_classifications", ()))
        receipt_id = canonical_hash(payload)
        payload["fallback_from"] = tuple(payload["fallback_from"])
        payload["error_classifications"] = tuple(payload["error_classifications"])
        return cls(**payload, receipt_id=receipt_id)

    def public_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class VoiceTranscriptionRequest:
    audio: bytes
    content_type: str
    language: str
    correlation_id: str

    @property
    def audio_sha256(self) -> str:
        return sha256_bytes(self.audio)


@dataclass(frozen=True)
class VoiceTranscriptionReceipt:
    provider_id: str
    model_id: str
    correlation_id: str
    audio_sha256: str
    transcript_sha256: str
    total_latency_ms: float
    receipt_id: str


@runtime_checkable
class VoiceProvider(Protocol):
    @property
    def manifest(self) -> VoiceProviderManifest: ...

    def synthesize(
        self, request: VoiceSynthesisRequest, resolve_credential: CredentialResolver
    ) -> VoiceArtifact: ...


@dataclass(frozen=True)
class AuditionCorpusEntry:
    entry_id: str
    category: str
    language: str
    text: str


@dataclass
class VoiceComparisonRecord:
    candidate_id: str
    provider_id: str
    model_id: str
    voice_id: str
    corpus_entry_id: str
    sample_path: str
    input_sha256: str
    audio_sha256: str
    byte_length: int
    first_audio_latency_ms: float
    total_latency_ms: float
    fallback_from: str = ""
    error_classifications: str = ""
    warmth: str = ""
    youthful_adult: str = ""
    brightness: str = ""
    articulation: str = ""
    natural_indonesian: str = ""
    english_code_switching: str = ""
    emotional_presence: str = ""
    robotic_tendency: str = ""
    shrill_tendency: str = ""
    overly_seductive_tendency: str = ""
    overall_score: str = ""
    founder_notes: str = ""
    disposition: str = ""

    def public_dict(self) -> dict[str, object]:
        return asdict(self)


def safe_sample_path(root: Path, *parts: str) -> Path:
    safe = ["".join(c if c.isalnum() or c in "._-" else "_" for c in part) for part in parts]
    path = root.joinpath(*safe)
    if root.resolve() not in path.resolve().parents:
        raise ValueError("sample path escapes output root")
    return path
