# ADR-0040 — Founder Bring-Up and Sense Modality Continuity

**Status:** Accepted  
**Release:** MVP v0.19.1

## Context

Aether's initial architecture defines voice and Telegram as replaceable senses feeding one cognitive path. The v0.19 deterministic voice adapter test used a speech-producing echo cognition, but the real CLI sense demo used `AetherCognitiveGateway`. The gateway accepted `audio.transcript` yet lost the source modality before selecting an output expression, producing `text` instead of `speech`.

Gateway process startup also used port 8888 while all operator-console integration used port 8000.

## Decision

1. `AetherCognitiveGateway` preserves the originating perception modality in cognitive context.
2. `audio.transcript` and `telegram.voice.transcript` default to `speech`.
3. An explicit `response_modality` remains authoritative.
4. Voice adapters continue to reject non-speech expressions rather than silently coercing arbitrary modalities.
5. Gateway startup honors `HOST` and `PORT`, defaulting to local-only `127.0.0.1:8000`.
6. Founder bring-up is a separate operational patch, not a new architecture authority lane.

## Consequences

- the real cognitive gateway can complete transcript-to-speech-sink turns;
- text channels remain text;
- TTS remains replaceable and outside Core;
- all embedded/native consoles share one default Gateway address;
- a one-command first pulse can validate the integrated system before live credentials are introduced.
