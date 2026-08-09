"""Credentialed exact-text voice worker (non-activation slice).

A source-present worker path that performs ONE governed exact-text synthesis
through the Founder Alpha Gemini deployment with a credential resolved from the
environment (never a raw value). It produces a hash-only turn receipt and, on
provider failure, an honest fallback proof (browser-speech/text-only) without
retrying the provider in a storm.

This module is intentionally NON-ACTIVATION: it never wires into the LiveKit
worker, never raises a capability to ACTIVE/CONFORMED/FOUNDER-PROVEN, and
refuses to execute a live provider call unless an explicit operator flag is
passed. Callers that need a real credentialless proof use the runtime directly.

Fallback semantics: ``selected_fallback=browser-speech`` is a client delivery
DIRECTIVE, not a server-side synthesis. The worker never synthesizes fallback
audio server-side; it only reports the honest directive so the client can speak
locally or fall through to text-only. No fallback audio is ever fabricated.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .adapters import GeminiExactTextTTSAdapter, HttpTransport, RequestsTransport
from .contracts import VoiceArtifact, VoiceSynthesisRequest
from .policy import BoundedVoicePromptCompiler, VoiceProfilePolicy
from .runtime import (
    ExactTextVoiceRuntime,
    VoiceDeploymentManifest,
    VoiceRuntimeResult,
    VoiceTurnRequest,
)

DEFAULT_MANIFEST = "configs/runtime/gemini_tts_founder_alpha.yaml"
DEFAULT_PERSONA = "aether-core/configs/persona.yaml"
_EXECUTE_FLAG = "AETHER_VOICE_WORKER_EXECUTE"


def _safe_stem(value: str) -> str:
    """Sanitize a caller-supplied identifier into a single safe path component."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", str(value or "")).strip("._-")
    if not cleaned:
        cleaned = "credentialed-worker"
    if cleaned in {"", ".", ".."} or "/" in cleaned or "\\" in cleaned:
        cleaned = "credentialed-worker"
    return cleaned[:120]


@dataclass(frozen=True)
class WorkerOutcome:
    request_accepted: bool
    outcome: str
    fallback_trigger_class: str
    selected_fallback: str
    receipt_id: str | None
    artifact_path: str | None
    speech_text_sha256: str
    audio_sha256: str
    provider_id: str
    model_id: str


class CredentialedVoiceWorker:
    """Run exactly one governed exact-text synthesis with an env-resolved credential.

    ``transport`` is injectable for deterministic tests. ``credential_loader``
    defaults to an env:// loader that refuses raw secrets.
    """

    def __init__(
        self,
        *,
        manifest_path: Path,
        persona_path: Path,
        transport: HttpTransport | None = None,
        credential_loader: Callable[[str], str] | None = None,
        output_root: Path | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.manifest_path = manifest_path
        self.persona_path = persona_path
        self.deployment = VoiceDeploymentManifest.from_yaml(manifest_path)
        self.policy = VoiceProfilePolicy.from_persona(persona_path)
        self.compiler = BoundedVoicePromptCompiler(self.policy)
        self.transport = transport or RequestsTransport(timeout_seconds=60)
        self.resolve_credential = credential_loader or self._env_credential
        self.output_root = output_root
        self.clock = clock or time.time

    @staticmethod
    def _env_credential(reference: str) -> str:
        if not reference.startswith("env://"):
            raise ValueError("voice worker accepts only env:// credential references")
        name = reference[len("env://"):]
        value = os.environ.get(name)
        if not value:
            raise RuntimeError(f"credential reference is not configured: {reference}")
        return value

    def readiness(self) -> dict[str, object]:
        livekit_gateway = bool(
            os.environ.get("LIVEKIT_URL")
            and os.environ.get("LIVEKIT_API_KEY")
            and os.environ.get("LIVEKIT_API_SECRET")
        )
        return {
            "worker": "aether.voice.credentialed.v1",
            "deployment_class": self.deployment.deployment_class,
            "runtime_profile": self.deployment.runtime_profile,
            "provider_id": self.deployment.provider.provider_id,
            "model_id": self.deployment.provider.model_id,
            "voice_id": self.deployment.provider.voice_id,
            "billing_tier": self.deployment.provider.billing_tier,
            "audition_state": self.deployment.provider.audition_state,
            "fallback_order": list(self.deployment.fallback_order),
            "livekit_worker_wired": False,
            "livekit_gateway_configured": livekit_gateway,
            "activate_gate": os.environ.get(_EXECUTE_FLAG, "").strip().lower()
            in {"1", "true", "yes"},
            "credential_reference": self.deployment.provider.credential_ref,
            "credential_resolved": False,
        }

    def _runtime(self) -> ExactTextVoiceRuntime:
        adapter = GeminiExactTextTTSAdapter(self.deployment.provider, self.transport)
        return ExactTextVoiceRuntime(
            adapter,
            deployment=self.deployment,
            compiler=self.compiler,
            resolve_credential=self.resolve_credential,
            clock=self.clock,
        )

    def run(
        self,
        speech_text: str,
        *,
        correlation_id: str,
        founder_alpha_consent: bool = False,
        delivery_preset_id: str | None = None,
        output_audio: bool = True,
    ) -> WorkerOutcome:
        text = str(speech_text or "").strip()
        if not text:
            raise ValueError("speech_text must not be empty")
        runtime = self._runtime()
        turn = VoiceTurnRequest(
            speech_text=text,
            correlation_id=correlation_id,
            founder_alpha_consent=founder_alpha_consent,
            delivery_preset_id=delivery_preset_id,
        )
        result = runtime.synthesize(turn)
        receipt = result.receipt
        artifact_path: str | None = None
        artifact: VoiceArtifact | None = result.artifact
        if output_audio and artifact is not None and self.output_root is not None:
            self.output_root.mkdir(parents=True, exist_ok=True)
            path = self.output_root / (
                f"{_safe_stem(receipt.correlation_id)}.{artifact.extension}"
            )
            if self.output_root.resolve() not in path.resolve().parents:
                raise ValueError("voice worker artifact path escapes the output root")
            path.write_bytes(artifact.audio)
            artifact_path = str(path)
        return WorkerOutcome(
            request_accepted=receipt.request_accepted,
            outcome=receipt.outcome,
            fallback_trigger_class=receipt.fallback_trigger_class,
            selected_fallback=receipt.selected_fallback,
            receipt_id=receipt.receipt_id,
            artifact_path=artifact_path,
            speech_text_sha256=receipt.speech_text_sha256,
            audio_sha256=receipt.audio_sha256,
            provider_id=receipt.provider_id,
            model_id=receipt.model_id,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", required=True)
    parser.add_argument("--correlation", default="credentialed-worker")
    parser.add_argument("--consent", action="store_true")
    parser.add_argument("--manifest", type=Path, default=Path(DEFAULT_MANIFEST))
    parser.add_argument("--persona", type=Path, default=Path(DEFAULT_PERSONA))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--execute", action="store_true", help="explicitly allow a live provider call")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    worker = CredentialedVoiceWorker(
        manifest_path=args.manifest,
        persona_path=args.persona,
        output_root=args.output,
    )
    readiness = worker.readiness()
    if args.dry_run or not (args.execute or readiness.get("activate_gate")):
        print(json.dumps(
            {
                "status": "dry-run",
                "execute_allowed": bool(args.execute or readiness.get("activate_gate")),
                "reason": "no live provider call without --execute",
                "readiness": readiness,
            },
            indent=2,
        ))
        return 0

    outcome = worker.run(
        args.text,
        correlation_id=args.correlation,
        founder_alpha_consent=args.consent,
        output_audio=args.output is not None,
    )
    print(json.dumps({
        "status": "completed",
        "outcome": outcome.outcome,
        "request_accepted": outcome.request_accepted,
        "fallback_trigger_class": outcome.fallback_trigger_class,
        "selected_fallback": outcome.selected_fallback,
        "receipt_id": outcome.receipt_id,
        "speech_text_sha256": outcome.speech_text_sha256,
        "audio_sha256": outcome.audio_sha256,
        "provider_id": outcome.provider_id,
        "model_id": outcome.model_id,
        "artifact_path": outcome.artifact_path,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
