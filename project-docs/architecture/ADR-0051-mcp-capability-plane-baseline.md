# ADR-0051 — MCP Capability Plane Baseline

- Status: Accepted for implementation
- Date: 2026-07-29
- Decision owner: Founder / Aether architecture
- Tracking issue: #3

## Context

Aether contains a dormant `FastMCP` prototype that reads a package-relative legacy CKA registry and exposes a legacy persona prompt. It is importable, but it is not connected to canonical `AETHER_HOME`, current governance, application services, a transport policy, or a conformance harness.

MCP and ACP have different responsibilities:

- ACP connects an agent to an editor or agent-facing user interface.
- MCP connects an AI host to tools, resources, and reusable context.

MCP is a connector and capability-description protocol. It is not an authority boundary and must not bypass Aether governance.

## Decision

Replace the legacy prototype with a first, hand-written **Aether Operational MCP** server.

The first server is projection-only and read-only. It exposes:

### Resources

- `aether://status`
- `aether://capabilities`
- `aether://handoff`

### Tools

- `aether_status`
- `aether_capability_manifest`
- `aether_handoff`
- `memory_search`
- `artifact_hash_verify`

### Prompt

- `aether_operational_context`, explicitly advisory and unable to replace the Aether system prompt, DNA, North Star, or governance.

## Security boundary

The baseline has no:

- mutation tools;
- approval decisions;
- shell access;
- arbitrary file reads;
- secret access;
- legacy CKA bulk access;
- public HTTP exposure.

Artifact hashing is restricted to the repository root and `AETHER_HOME`. Memory access uses bounded SQLite read-only connections and returns a reduced projection with provenance. A fresh `AETHER_HOME` must not be created by MCP reads.

## Transports

- `stdio` is enabled by default.
- Streamable HTTP requires explicit opt-in and is restricted to `127.0.0.1`, `::1`, or `localhost`.
- Cloudflare/public ingress is forbidden for this baseline.

## Dependency policy

Aether currently uses the MCP Python SDK v1 `mcp.server.fastmcp` API. The package remains bounded to `mcp>=1.27,<2`. Migration to MCP SDK v2 requires a separate compatibility ADR and conformance proof.

## Conformance

CI must prove:

1. MCP initialization over stdio;
2. exact tool/resource/prompt enumeration;
3. a successful read-only status call;
4. no state creation in a fresh `AETHER_HOME`;
5. non-loopback HTTP rejection;
6. bounded artifact and memory access.

## Deferred

The following are intentionally deferred until the first server is Founder-proven:

- external MCP client manager;
- MCP server registry and credential references;
- remote OAuth;
- proposal/mutation tools routed through `GovernedActionPath`;
- generic MCP Builder extraction.

The Builder will be extracted only after at least two real MCP integrations reveal stable repeated patterns.
