# ADR-0006 — Aether Cognitive Gateway and Unified Ingestion

**Status:** Accepted  
**Release:** MVP v0.3

## Context

The previous Telegram implementation selected models, owned conversation history, executed provider calls, parsed tool tags, performed file writes, and formatted responses inside the communication adapter. That made Telegram an accidental cognitive runtime and prevented voice, HTTP, desktop, and future interfaces from sharing one governed path.

Aether Core must remain model-provider and interface agnostic.

## Decision

1. `AetherCognitiveGateway` is owned by `aether-core` and implements `CognitivePort`.
2. It converts a governed `Perception` into a capability-based `ModelRequest`.
3. Concrete model routing, API keys, endpoints, and HTTP transport live in `aether-gateway` behind `ModelProvider`.
4. Short-term conversation context uses an injected `ConversationStore`; it is not persistent autobiographical memory.
5. Telegram text, Telegram voice transcripts, CLI, HTTP, voice, and future AionUi requests use `SenseEventPath`.
6. Communication adapters may transport or render expressions but may not perform cognition.
7. The durable event chain is:

```text
perception.received
  → cognition.requested
  → cognition.completed
  → expression.requested
  → expression.delivered
```

Failures emit `sense.path.failed` and are re-raised to the caller.

## Consequences

- Changing Telegram, AionUi, voice, or a model provider no longer changes Aether cognition.
- Model preference is metadata on a perception, not adapter-owned provider logic.
- Provider configuration was removed from Aether Core.
- Tool execution is deliberately not part of this release; it will enter through a governed body/tool execution port rather than Telegram-specific parsing.
