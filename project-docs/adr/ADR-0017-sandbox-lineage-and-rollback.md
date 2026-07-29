# ADR-0017 — Sandbox, Lineage, Promotion, and Rollback

**Status:** Accepted in MVP v0.8  
**Date:** 2026-07-28

## Decision

Core defines `EvolutionSandbox` and `EvolutionPromoter` ports. Concrete filesystem/process behavior belongs to Gateway adapters.

The local MVP sandbox copies the configured workspace into separate baseline and candidate directories. Commands use `create_subprocess_exec`, never a shell, and are limited to `python -m pytest`, `python -m unittest`, or `python -m compileall`.

Promotion checks that the production artifact still matches the recorded baseline hash, writes a backup, writes the exact candidate content to a temporary file, and atomically replaces the target. Rollback is permitted only when the current production artifact still matches the promoted hash.

## Durable state

SQLite stores immutable triggers, candidates, evaluations, terminal decisions, lineage, rollback records, and learnings. Candidate state is derived from those append-only records.

## Boundaries

The local sandbox isolates files and limits commands, but does not provide OS-level network, kernel, credential, or process isolation. A Docker, microVM, or remote sandbox adapter is required before untrusted autonomous candidate execution is enabled.
