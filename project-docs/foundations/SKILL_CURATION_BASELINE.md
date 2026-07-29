# Aether Skill Curation Baseline

Status: ACCEPTED FOUNDATION
Date: 2026-07-29

## Current truth

Aether already has a governed Skill Factory with candidate provenance, deterministic and held-out benchmarks, trusted activation decisions, immutable learning records, usage telemetry, lifecycle review, stale/archive states, and a rule preventing repetition of the same failed candidate without an explicit reason.

The missing layer is external skill discovery and curation. Current runtime execution supports Aether-native template skills and does not safely execute an arbitrary third-party skill repository.

## External skill intake lifecycle

`discovered -> snapshotted -> classified -> normalized -> sandboxed -> benchmarked -> approved -> activated -> observed -> revised/archived`

No external skill is installed directly into an active runtime.

## ExternalSkillCandidate requirements

- repository and immutable commit SHA
- skill file path and SHA-256
- version and license
- author/publisher identity
- requested tools and side effects
- runtime and binary requirements
- environment/credential requirements
- network destinations and data classes
- install/update behavior
- test evidence and security posture
- freshness and upstream drift
- Aether capability mapping

## Curation policy

1. Pin exact commit or release; never execute floating `main`.
2. Preserve source snapshot and provenance.
3. Reject self-updating behavior inside active execution.
4. Quarantine credential acquisition and browser-session extraction.
5. Convert host-specific prompt instructions into Aether contracts where practical.
6. Separate source adapters, ranking logic, synthesis policy, and output presentation.
7. Require deterministic and held-out benchmarks.
8. Require Founder activation for side-effecting or credential-bearing skills.
9. Continuously compare installed hash with upstream, but never auto-upgrade.
10. Retain previous active artifact for rollback.

## `last30days-skill` disposition

Do not install it directly into Aether now.

Reasons:

- it is a large host-oriented instruction contract with scripts and many optional sources/credentials
- it assumes Bash/Read/Write/WebSearch-style host tools
- it contains source setup, browser/cookie, API-key, and updater concerns
- current Aether skill runtime cannot execute this repository as a governed native skill

Use it as a reference implementation and nutrition source for an Aether-native candidate:

`recent-signal-research`

Decompose into:

1. recent-window research request contract
2. governed source-adapter selection
3. provenance and freshness snapshotting
4. engagement/economic-signal scoring
5. cross-source contradiction handling
6. bounded synthesis with citations
7. source health/doctor report

This candidate should run over Aether SourceCapabilityMesh rather than receiving unrestricted shell or browser authority.
