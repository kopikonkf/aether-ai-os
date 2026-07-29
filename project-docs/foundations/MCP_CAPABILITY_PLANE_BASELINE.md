# Aether MCP Capability Plane Baseline

## Current truth

Aether now has a first read-only operational MCP implementation candidate. It replaces the dormant package-relative legacy CKA prototype.

Capability state before Founder proof:

```text
MCP SDK dependency              IMPLEMENTED
Read-only operational service  IMPLEMENTED
FastMCP server                 IMPLEMENTED
stdio transport                WIRED
loopback Streamable HTTP       WIRED, explicit opt-in only
protocol conformance           CI REQUIRED
external MCP client manager    NOT IMPLEMENTED
remote OAuth                   NOT IMPLEMENTED
mutation/proposal tools        NOT IMPLEMENTED
MCP Builder                    NOT IMPLEMENTED
```

## Authority model

```text
MCP client
   ↓
Aether Operational MCP
   ↓ read-only projections
Repository handoff / memory projection / artifact hashing
```

MCP does not become a new authority. It cannot write Aether state, approve actions, execute shell commands, or replace system identity and governance.

## First Founder proof

A trusted local MCP client such as Codex should:

1. initialize the `aether-mcp` stdio server;
2. list the exact approved capabilities;
3. read `aether://handoff`;
4. call `aether_status`;
5. perform one bounded `memory_search` against the migrated `AETHER_HOME`;
6. verify one known artifact hash;
7. leave Aether state unchanged.

After this proof, the next MCP lane is an external MCP client manager with server identity, schema hashes, trust tiers, health, and credential references. Mutation tools remain proposals routed through the existing governed action path.
