# ADR-0036 — Web Intelligence Substrate and Source Capability Mesh

## Status

Accepted for MVP v0.18.

## Context

Aether requires continuous external nutrition: public web pages, catalogs, feeds, repositories, platforms, and future search providers. Coupling Core to one crawler or search API would violate runtime/provider independence and prevent source evolution.

## Decision

Create provider-neutral source contracts in Core and concrete acquisition adapters in Gateway.

Crawl4AI is classified as a **Web Intelligence Substrate**. It remains optional and replaceable behind `Crawl4AIRestrictedAdapter`. Core never imports Crawl4AI.

A source capability mesh owns manifests, health probes, priority, capability matching, and bounded fallback. This pattern is inspired by Agent-Reach, but Aether retains its own governance and does not grant an installer or upstream shell command direct authority.

Catalog sources are differentiated from market evidence:

- AI TreasureBox: continuous technology curriculum;
- Awesome AI Agents: market/capability taxonomy;
- catalog popularity: weak or moderate evidence;
- customer demand: requires independent external validation.

## Security profile

Public acquisition is allowed within resource policy. Private networks, local files, credential export, arbitrary generated JavaScript, persistent browser profiles, downloads, and unbounded recursion are denied by default.

## Consequences

Aether can expand its senses without changing Mind/Soul. Missing Crawl4AI does not block boot. Every snapshot remains attributable to an adapter and policy fingerprint.
