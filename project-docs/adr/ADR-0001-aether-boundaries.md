# ADR-0001: Aether Owns Mind and Soul; Runtimes and Senses Are Adapters

- Status: Accepted
- Date: 2026-07-27
- Scope: MVP v0.1

## Decision

Aether Core owns identity, constitution, governance, goals, cognition, event semantics, and evolution policy. It exposes stable capability contracts. It does not import a desktop shell, voice SDK, model SDK, memory database, or concrete agent runtime.

External components are classified as:

1. **Runtime adapters (body):** execute commands and tools.
2. **Sense adapters (eyes, ears, mouth):** produce perceptions and consume expressions.
3. **Model providers:** satisfy cognitive capabilities such as reasoning, planning, criticism, vision, and coding.
4. **Memory providers:** persist and retrieve records through a storage-neutral contract.
5. **Shells:** desktop, web, Telegram, or mobile interfaces that display state and collect input.

A desktop cowork application may host Aether, but it must not become Aether's identity or cognitive source of truth.

## Consequences

- A voice stack can be replaced without changing cognition.
- A desktop shell can be upgraded or removed without migrating identity.
- A runtime can fail over to another runtime through capability routing.
- Memory can move from local files to SQLite, vector stores, graph stores, or remote services.
- CEE can later operate across both internal OS evolution and external business execution using the same event and governance boundaries.

## Explicit Non-Decisions

CEE mechanics are not finalized in v0.1. Ralph-style iteration is accepted as research input, not copied as the final evolution architecture.
