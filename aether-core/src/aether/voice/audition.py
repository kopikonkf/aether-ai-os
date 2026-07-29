"""Audition orchestration, fallback detection, and comparison-sheet generation."""
from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Iterable, Sequence

from aether.resilience import (
    ProviderCandidate,
    ProviderErrorSignal,
    classify_provider_error,
    fallback_eligible_error,
    select_fallback,
)

from .contracts import (
    AuditionCorpusEntry,
    CredentialResolver,
    VoiceComparisonRecord,
    VoiceProvider,
    VoiceSynthesisReceipt,
    VoiceSynthesisRequest,
    safe_sample_path,
    sha256_bytes,
)


class AuditionFailed(RuntimeError):
    pass


class AuditionRunner:
    def __init__(
        self,
        providers: Sequence[VoiceProvider],
        *,
        resolve_credential: CredentialResolver,
        clock: Callable[[], float],
        candidate_state: Callable[[VoiceProvider], ProviderCandidate] | None = None,
    ) -> None:
        self.providers = tuple(providers)
        self.resolve_credential = resolve_credential
        self.clock = clock
        self.candidate_state = candidate_state or self._default_candidate

    @staticmethod
    def _default_candidate(provider: VoiceProvider) -> ProviderCandidate:
        manifest = provider.manifest
        return ProviderCandidate(
            provider_id=manifest.provider_id,
            priority=manifest.priority,
            capabilities=manifest.capabilities,
            data_policy_tags=manifest.data_policy_tags,
        )

    @staticmethod
    def _signal(error: Exception) -> ProviderErrorSignal:
        return ProviderErrorSignal(
            status_code=getattr(error, "status_code", None),
            error_code=getattr(error, "error_code", ""),
            message=str(error),
            retry_after_seconds=getattr(error, "retry_after_seconds", None),
            exception_name=type(error).__name__,
        )

    def synthesize(
        self,
        request: VoiceSynthesisRequest,
        *,
        allowed_data_policy_tags: Iterable[str],
    ) -> tuple[object, VoiceSynthesisReceipt]:
        provider_by_id = {provider.manifest.provider_id: provider for provider in self.providers}
        remaining = list(self.providers)
        fallback_from: list[str] = []
        errors: list[str] = []
        attempts = 0
        while remaining:
            decision = select_fallback(
                [self.candidate_state(provider) for provider in remaining],
                required_capabilities={"voice.tts"},
                allowed_data_policy_tags=allowed_data_policy_tags,
                now=self.clock(),
            )
            selected_id = decision.selected_provider_id
            if selected_id is None:
                break
            provider = provider_by_id[selected_id]
            started = self.clock()
            attempts += 1
            try:
                artifact = provider.synthesize(request, self.resolve_credential)
            except Exception as error:
                kind = classify_provider_error(self._signal(error))
                errors.append(f"{selected_id}:{kind.value}")
                if not fallback_eligible_error(kind):
                    raise
                fallback_from.append(selected_id)
                remaining = [item for item in remaining if item.manifest.provider_id != selected_id]
                continue
            completed = self.clock()
            latency = (completed - started) * 1000
            manifest = provider.manifest
            receipt = VoiceSynthesisReceipt.build(
                provider_id=manifest.provider_id,
                model_id=manifest.model_id,
                voice_id=manifest.voice_id,
                correlation_id=request.correlation_id,
                input_sha256=request.input_sha256,
                audio_sha256=sha256_bytes(artifact.audio),
                byte_length=len(artifact.audio),
                content_type=artifact.content_type,
                output_format=manifest.output_format,
                started_at=started,
                first_audio_latency_ms=latency,
                total_latency_ms=latency,
                attempt_count=attempts,
                fallback_from=tuple(fallback_from),
                error_classifications=tuple(errors),
            )
            return artifact, receipt
        raise AuditionFailed("no eligible voice provider completed synthesis")

    def generate(
        self,
        corpus: Iterable[AuditionCorpusEntry],
        output_root: Path,
        *,
        allowed_data_policy_tags: Iterable[str] = ("hosted", "local"),
    ) -> list[VoiceComparisonRecord]:
        output_root.mkdir(parents=True, exist_ok=True)
        records: list[VoiceComparisonRecord] = []
        for entry in corpus:
            request = VoiceSynthesisRequest(
                text=entry.text,
                language=entry.language,
                correlation_id=f"audition:{entry.entry_id}",
            )
            artifact, receipt = self.synthesize(
                request, allowed_data_policy_tags=allowed_data_policy_tags
            )
            candidate_id = f"{receipt.provider_id}__{receipt.voice_id}"
            path = safe_sample_path(
                output_root, candidate_id, f"{entry.entry_id}.{artifact.extension}"
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(artifact.audio)
            receipt_path = path.with_suffix(path.suffix + ".receipt.json")
            receipt_path.write_text(
                json.dumps(receipt.public_dict(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            records.append(
                VoiceComparisonRecord(
                    candidate_id=candidate_id,
                    provider_id=receipt.provider_id,
                    model_id=receipt.model_id,
                    voice_id=receipt.voice_id,
                    corpus_entry_id=entry.entry_id,
                    sample_path=str(path.relative_to(output_root)),
                    input_sha256=receipt.input_sha256,
                    audio_sha256=receipt.audio_sha256,
                    byte_length=receipt.byte_length,
                    first_audio_latency_ms=receipt.first_audio_latency_ms,
                    total_latency_ms=receipt.total_latency_ms,
                    fallback_from=",".join(receipt.fallback_from),
                    error_classifications=",".join(receipt.error_classifications),
                )
            )
        write_comparison_sheets(records, output_root)
        return records


def write_comparison_sheets(
    records: Sequence[VoiceComparisonRecord], output_root: Path
) -> None:
    rows = [record.public_dict() for record in records]
    (output_root / "voice-comparison.json").write_text(
        json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    fields = list(VoiceComparisonRecord.__dataclass_fields__)
    with (output_root / "voice-comparison.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    scored = [
        "candidate_id",
        "corpus_entry_id",
        "sample_path",
        "audio_sha256",
        "total_latency_ms",
        "warmth",
        "youthful_adult",
        "brightness",
        "articulation",
        "natural_indonesian",
        "english_code_switching",
        "emotional_presence",
        "robotic_tendency",
        "shrill_tendency",
        "overly_seductive_tendency",
        "overall_score",
        "founder_notes",
        "disposition",
    ]
    lines = [
        "# Aether Voice Audition Comparison",
        "",
        "Scores are Founder-entered. Audio identity is bound by SHA-256.",
        "",
        "| " + " | ".join(scored) + " |",
        "|" + "|".join("---" for _ in scored) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(row[field]).replace("|", "\\|") for field in scored) + " |")
    (output_root / "voice-comparison.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
