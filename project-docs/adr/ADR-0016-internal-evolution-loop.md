# ADR-0016 — Governed Internal Evolution Loop

**Status:** Accepted in MVP v0.8  
**Date:** 2026-07-28

## Decision

Aether will implement internal evolution as a governed evidence loop, not as an unrestricted self-editing agent.

A trigger is either a verified failure or an explicit capability gap. The trigger receives a deterministic fingerprint and recalls prior durable learnings. One candidate may modify one bounded artifact. The candidate includes the baseline, replacement content, unified diff, generator identity, deterministic checks, and held-out checks.

Candidate generation is a replaceable port and is never authoritative. Promotion requires a trusted operator decision after evaluation.

## Ralph concepts adapted

- one bounded task per iteration;
- fresh execution context for every attempt;
- durable progress outside model context;
- explicit completion, blocked, and decision states;
- tests before completion;
- maximum bounded iteration behavior;
- human steering and auditability.

## Ralph concepts not adopted directly

- coding-only objective scope;
- shell scripts as architecture authority;
- bypass-permission execution;
- commits as the only durable state;
- arbitrary terminal access for the optimizing model;
- prompt-only safety boundaries.

## Consequences

The loop is slower than direct self-editing, but failures, candidate provenance, evaluation evidence, promotion decisions, and rollback points remain inspectable and reproducible.
