# ADR-0004 — Sense Event Path

**Status:** Implemented  
**Date:** 2026-07-28

## Decision

Every communication or perception adapter produces `Perception` objects. Aether Core owns the causal orchestration:

`Perception → perception.received → cognition.requested → CognitivePort → expression.requested → SenseAdapter.express`

The complete turn shares one correlation ID and records causation IDs in the durable event journal.

## Boundaries

- STT, TTS, microphone, camera, realtime providers, Telegram, and desktop shells remain adapters.
- The cognition implementation is a replaceable `CognitivePort`.
- The smoke-test cognition adapter is deterministic and not production intelligence.
- Memory persistence is not coupled to the sense path; memory will subscribe to governed events later.

## Verification

`python aether_cli.py sense-demo --text "Halo Aether"`
