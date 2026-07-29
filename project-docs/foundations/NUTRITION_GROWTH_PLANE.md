# Aether Nutrition Growth Plane

Status: ACCEPTED FOUNDATION
Date: 2026-07-30
Founder: Dee

## Purpose

Aether is still early in her development. The Nutrition Growth Plane exists to help her acquire evidence, access paths, reusable capabilities, and worker patterns without treating arbitrary external repositories as trusted identity, memory, authority, or production code.

Growth must be evidence-backed, reversible, attributable, benchmarked, and governed.

```text
external discovery
→ immutable snapshot
→ classification
→ quarantine
→ policy conformance
→ Aether-native normalization
→ deterministic and held-out benchmark
→ Founder decision
→ bounded activation
→ observation
→ revise/archive/rollback
```

No external repository is installed directly into active Aether merely because it is useful or popular.

## Plane boundaries

### 1. Discovery and catalog nutrition

Purpose: discover candidate tools, patterns, libraries, skills, and agents.

Examples:

- `superiorlu/AITreasureBox`
- `jim-schwoebel/awesome_ai_agents`

Disposition:

- catalog/evidence feeds;
- snapshot exact commits and relevant files;
- extract candidate references and metadata;
- never execute catalog content;
- never equate stars, ranking, or popularity with conformance;
- promote individual candidates only through a separate intake.

### 2. Source access and observation

Purpose: obtain bounded public evidence from the outside world.

Examples:

- `unclecode/crawl4ai`
- Agent-Reach-inspired channel/backend routing
- public HTTP, search, RSS, GitHub, YouTube transcript, and future source adapters

Authority remains in Aether. External tools are replaceable substrates behind `SourceCapabilityMesh`.

### 3. Interpretation and nutrition curation

Purpose: turn source snapshots into provenance-bearing claims, contradictions, candidate knowledge, opportunity evidence, and normalized skill proposals.

This plane must preserve:

- source identity;
- retrieval time;
- content hash;
- adapter manifest hash;
- source-conformance receipt;
- bounded extraction method;
- contradiction evidence;
- uncertainty;
- candidate lineage.

### 4. Skill and capability growth

Purpose: normalize an external idea into an Aether-owned skill or capability contract.

A passing nutrition receipt means only:

```text
eligible_for_benchmark = true
eligible_for_activation = false
```

Activation remains a separate Skill Factory and Founder decision.

### 5. Runtime-body growth

Purpose: add or improve replaceable workers such as OpenCode, Codex, Gemini CLI, Claude Code, or future runtimes.

Runtime bodies are not skills, memory, or identity. They require their own driver manifest, staging boundary, capability conformance, cancellation, independent verification, telemetry, and approval receipts.

### 6. Autonomous bounded execution

Purpose: let Aether repeatedly pursue a bounded objective while maintaining explicit budgets and stop conditions.

The current `AutonomousOpportunityScout` is observational only:

```text
SourceCapabilityMesh
→ health and eligibility
→ bounded search/fetch
→ immutable snapshots
→ bounded claim extraction
→ opportunity evidence receipts
```

Observation never grants mutation authority.

## SourceCapabilityMesh

`SourceCapabilityMesh` is Aether's health-aware ordered registry of source adapters.

It provides:

- adapter registration by stable ID;
- immutable capability manifests;
- health checks;
- ordered priority;
- source-kind filtering;
- public-observation policy;
- conformance eligibility guards;
- bounded source selection per query;
- replaceable primary/fallback substrates.

It does not:

- become Aether's source of truth;
- install third-party packages automatically;
- expose cookies or credentials to the model;
- grant filesystem, shell, or private-network access;
- activate a skill or runtime;
- approve mutations.

## External repository intake mechanism

When Dee supplies a repository URL and asks Aether to use or install it, the first action is classification.

### Classification types

1. `source-adapter` — fetches/searches external evidence.
2. `catalog-feed` — contains references or curated lists.
3. `skill-candidate` — reusable instructions/workflow to normalize.
4. `runtime-body` — coding or execution agent/CLI.
5. `library-dependency` — implementation library behind an Aether-owned adapter.
6. `execution-loop-pattern` — orchestration design such as Ralph.
7. `application` — standalone product requiring a separate integration boundary.

### Intake sequence

```text
repository URL
→ resolve exact commit
→ inspect license and provenance
→ hash selected artifacts
→ classify authority and side effects
→ declare runtime/network/credential/install/update requirements
→ reject forbidden authority
→ create ExternalNutritionCandidate
→ quarantine checkout/environment
→ build Aether-native adapter/skill/driver contract
→ deterministic checks
→ held-out checks
→ exact conformance receipt
→ Founder approval
→ install only into the declared boundary
→ retain rollback artifact
```

### Forbidden direct-install behavior

Aether must not directly run an upstream install instruction that requests:

- arbitrary shell;
- unrestricted filesystem writes;
- system package installation without explicit provisioning approval;
- self-update/auto-upgrade;
- browser-cookie or session extraction;
- credential export;
- private-network access;
- persistent browser profiles;
- arbitrary model-generated JavaScript;
- permission bypass flags.

## Upstream dispositions

### Crawl4AI

Classification: `library-dependency` behind a `source-adapter`.

Current Aether source already contains `Crawl4AIRestrictedAdapter` with:

- public HTTP(S)-only targets;
- private/loopback/link-local denial;
- maximum bytes;
- bounded timeout;
- no file scheme;
- no credential export;
- no filesystem downloads;
- no persistent browser profile;
- no arbitrary model-generated JavaScript;
- no unbounded recursion.

Current state:

```text
adapter source       IMPLEMENTED
composition wiring   partial/reference
package installed    NOT PROVEN
live conformance     NOT PROVEN
ACTIVE               NO
FOUNDER-PROVEN       NO
```

Activation sequence:

```text
pin Crawl4AI version/commit
→ isolated dependency environment
→ adapter manifest verification
→ public-target SSRF tests
→ bounded crawl fixtures
→ live-source conformance receipt
→ SourceCapabilityMesh eligibility
→ Founder canary
```

### Agent Reach

Classification: `capability-routing pattern` plus upstream-tool catalog.

Do not install Agent Reach directly into production Aether because its standard workflow can install CLIs/system dependencies, register skills, use shell execution, configure MCP services, work with browser sessions/cookies, and update routing backends.

Nutrition value to retain:

- one channel maps to an ordered primary/fallback backend list;
- real health probes, not executable-presence checks;
- doctor output with fix prescriptions;
- access paths can be replaced without changing the calling capability;
- configure only requested channels;
- separate zero-config public observation from authenticated/session-bearing access.

Aether-native normalization target:

```text
SourceCapabilityMesh
+ SourceAdapterManifest
+ exact live-source conformance receipts
+ credential references outside model context
+ Founder-approved channel activation
```

### AITreasureBox

Classification: `catalog-feed`.

Use for discovery and ranking signals only. Its generated rankings and frequent updates are evidence for candidate discovery, not evidence of safety, quality, compatibility, or activation eligibility.

### awesome_ai_agents

Classification: `catalog-feed` and architecture research corpus.

Use to identify candidate frameworks, benchmarks, memory systems, agent runtimes, security/testing patterns, and market categories. Individual linked projects require separate immutable intake.

## Aether-native Ralph-style action loop

Ralph is useful as an `execution-loop-pattern`, not as a script to copy unchanged into production.

Valuable principles:

- one small story per iteration;
- fresh worker context each iteration;
- durable progress in Git/issue/task receipts;
- explicit acceptance checks;
- tests and CI as feedback loops;
- append reusable learnings to `AGENTS.md`;
- stop when all bounded stories pass or iteration/time/budget limit is reached.

Unsafe upstream behavior that Aether must not copy:

- `--dangerously-allow-all`;
- `--dangerously-skip-permissions`;
- unrestricted commits;
- direct mutation of production workspaces;
- implicit trust in worker completion text;
- unbounded iteration/retry.

Aether-native loop:

```text
Founder-approved Mission/Issue/PRD
→ immutable task envelope
→ bind staging workspace and branch
→ choose highest-priority incomplete story
→ dispatch one conformed worker body
→ collect structured patch/artifacts
→ independently run declared verification
→ route mutations through Approval Inbox when required
→ commit/PR receipt
→ append bounded learning/checkpoint
→ evaluate stop conditions and budgets
→ next fresh iteration or halt
```

Completion must be determined from authoritative task state and verification receipts, not only a textual `<promise>COMPLETE</promise>` signal.

## CLI relationship

The root `aether_cli.py` is currently a broad developer/Founder verification harness. It already proves many internal paths, including cognition, senses, approvals, memory, skill factory, evolution, runtime drivers, and live-driver demos.

It is not yet the stable installed umbrella command `aether`.

The stable CLI should expose this growth plane through thin service calls:

```text
aether nutrition inspect <repo>
aether nutrition status <candidate>
aether nutrition conform <candidate>
aether sources status
aether sources doctor
aether sources enable <adapter>
aether scout run <objective>
aether runtime conform <driver>
aether loop status <mission>
aether loop run <mission> --max-iterations N
```

All mutations and activations must use the same governance, exact action binding, Approval Inbox, and receipt contracts as Telegram and AionUi.

## Voice reference

Canonical persona v3 voice target:

```text
feminine
warm
youthful-adult
bright
articulate
not childish
not shrill
not robotic
not overly seductive
```

Founder reference:

```text
https://www.youtube.com/watch?v=XjSltll-ESM
```

The URL is an audition reference only. It does not prove a specific Google voice ID, API availability, licensing, or exact acoustic match. Dee retains preview, lock, veto, and fallback control.

## Delivery sequence

```text
provider resilience contracts
→ Google TTS audition/fallback tooling
→ OpenCode runtime-body conformance
→ release/VPS evidence automation
```

Parallel Nutrition Growth Plane activation:

```text
Crawl4AI restricted dependency pin and conformance
→ Agent-Reach-inspired channel registry/doctor normalization
→ bounded autonomous scout Founder proof
→ stable Aether CLI growth commands
→ bounded Ralph-style mission loop
```

Host activation and public ingress remain subject to VPS provisioning, service supervision, migration, and Founder acceptance.