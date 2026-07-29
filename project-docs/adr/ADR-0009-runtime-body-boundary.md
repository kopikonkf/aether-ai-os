# ADR-0009 — Runtime Body Boundary

**Status:** Accepted  
**Release:** MVP v0.4

## Decision

A runtime is an interchangeable body adapter implementing `RuntimeAdapter`:

```python
capabilities()
health()
execute(RuntimeCommand) -> RuntimeResult
```

Core selects only capability and command contracts. Concrete process creation, SDK calls, credentials, runtime sessions, and vendor-specific behavior remain in Gateway adapters.

## MVP reference body

`LocalProcessRuntimeAdapter` proves real runtime delegation across Windows, Linux, and macOS.

It exposes only `echo`, starts `sys.executable` with `create_subprocess_exec`, uses no shell, applies a timeout, captures stdout/stderr, and rejects every non-allowlisted command.

This adapter is not a substitute for Claude Code, Codex, OpenCode, Cursor, or other external runtime adapters. Those implement the same contract outside Core.

## Tool boundary

`RegistryToolExecutor` translates the existing `ToolRegistry` into Core's `ToolExecutor` port. Tool scopes and reversibility are declared at the adapter boundary. Tool implementation packages do not become Core dependencies.

## Consequences

- provider and runtime selection remain replaceable;
- external execution has a durable causal trace;
- unsafe capabilities can exist in a registry without being governance-approved;
- runtime health and capabilities can be inspected independently;
- arbitrary command strings are not accepted by the MVP body.
