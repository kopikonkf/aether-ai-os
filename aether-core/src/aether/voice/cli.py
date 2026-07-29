"""Explicit live voice audition CLI. No provider call occurs without --execute-live."""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from .adapters import (
    CartesiaTTSAdapter,
    GoogleCloudTTSAdapter,
    OpenAIExactTextTTSAdapter,
    RequestsTransport,
)
from .audition import AuditionRunner
from .contracts import AuditionCorpusEntry, VoiceProviderManifest


CORPUS = (
    AuditionCorpusEntry(
        "natural-id",
        "natural_indonesian",
        "id-ID",
        "Selamat pagi, Dee. Saya sudah memeriksa sistem dan semuanya siap.",
    ),
    AuditionCorpusEntry(
        "code-switch",
        "english_code_switching",
        "id-ID",
        "Rencananya sudah solid. Next, kita verify latency dan fallback receipt.",
    ),
    AuditionCorpusEntry(
        "warm-support",
        "emotional_presence",
        "id-ID",
        "Tidak apa-apa berjalan pelan. Kita tetap jaga bukti, arah, dan langkah berikutnya.",
    ),
    AuditionCorpusEntry(
        "technical",
        "articulation",
        "id-ID",
        "Circuit breaker terbuka setelah ambang kegagalan tercapai, lalu mengizinkan satu probe.",
    ),
)


def _manifest(raw: dict) -> VoiceProviderManifest:
    return VoiceProviderManifest(
        provider_id=str(raw["provider_id"]),
        model_id=str(raw["model_id"]),
        voice_id=str(raw["voice_id"]),
        language=str(raw.get("language") or "id-ID"),
        output_format=str(raw.get("output_format") or "mp3"),
        credential_ref=str(raw["credential_ref"]),
        priority=int(raw["priority"]),
        capabilities=frozenset(raw.get("capabilities") or {"voice.tts"}),
        streaming=bool(raw.get("streaming", False)),
        data_policy_tags=frozenset(raw.get("data_policy_tags") or {"hosted"}),
        cost_class=str(raw.get("cost_class") or "metered"),
    )


def _resolve_credential(reference: str) -> str:
    prefix = "env://"
    if not reference.startswith(prefix):
        raise ValueError("live audition accepts only env:// credential references")
    name = reference[len(prefix) :]
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"credential reference is not configured: {reference}")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute-live", action="store_true")
    args = parser.parse_args(argv)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if not args.execute_live:
        print(
            json.dumps(
                {
                    "status": "dry-run",
                    "provider_count": len(config.get("providers") or []),
                    "corpus_count": len(CORPUS),
                    "message": "No provider call made. Pass --execute-live explicitly.",
                },
                indent=2,
            )
        )
        return 0

    transport = RequestsTransport(timeout_seconds=float(config.get("timeout_seconds") or 60))
    providers = []
    for raw in config.get("providers") or []:
        manifest = _manifest(raw)
        adapter = str(raw["adapter"])
        adapter_type = {
            "google-cloud-tts": GoogleCloudTTSAdapter,
            "openai-exact-tts": OpenAIExactTextTTSAdapter,
            "cartesia-tts": CartesiaTTSAdapter,
        }.get(adapter)
        if adapter_type is None:
            raise ValueError(f"unsupported audition adapter: {adapter}")
        providers.append(adapter_type(manifest, transport))

    runner = AuditionRunner(
        providers,
        resolve_credential=_resolve_credential,
        clock=time.time,
    )
    records = runner.generate(CORPUS, args.output)
    print(
        json.dumps(
            {
                "status": "completed",
                "sample_count": len(records),
                "output": str(args.output),
                "comparison_files": [
                    "voice-comparison.json",
                    "voice-comparison.csv",
                    "voice-comparison.md",
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
