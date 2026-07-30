# Voice Audition and Runtime Resilience

Status: IMPLEMENTED/WIRED SOURCE CANDIDATE; LIVE ACTIVATION EVIDENCE REQUIRED

Date: 2026-07-30

Founder: Dee

## Decision

Voice audition and runtime resilience share PR #22's provider-neutral taxonomy
and fallback eligibility rules, but remain separate authorities:

```text
Aether Gateway cognition
→ AETHER_HOME provider state
→ capability/budget/circuit decision
→ selected model route
→ exact ModelResponse

LiveKit media worker
→ ordered STT fallback
→ Aether Gateway exact cognition
→ ordered TTS fallback
→ browser audio

Voice audition CLI
→ fixed corpus
→ provider adapter
→ audio + SHA-256/latency receipt
→ JSON/CSV/Markdown comparison sheets
```

Voice providers do not receive tool or mutation authority. LiveKit remains the
media plane; Aether Gateway remains the only cognitive authority.

## Persistent state

When `AETHER_PROVIDER_RESILIENCE_ENABLED=true`, Gateway cognition stores state
under:

```text
${AETHER_HOME}/runtime/provider-resilience.sqlite3
```

The database owns:

- UTC daily request consumption;
- current concurrency;
- circuit state and consecutive failures;
- open/cooldown times;
- hash-bound fallback decision receipts.

Source checkout directories never own this state.

## Cognition wiring

The existing configured model router retains the ordered routes in
`llm_providers.yaml`. With resilience enabled, selection additionally requires:

- matching cognition capability;
- enabled provider profile;
- remaining daily budget;
- available concurrency;
- non-open circuit/cooldown;
- permitted data-policy tags.

Native provider failures are normalized to `ProviderErrorSignal`. A fallback is
eligible only when allowed by the PR #22 taxonomy. Invalid request and unknown
failure classes fail closed.

## LiveKit wiring

Primary models remain:

```dotenv
AETHER_STT_MODEL=...
AETHER_TTS_MODEL=...
AETHER_TTS_VOICE=...
```

Ordered fallback models are explicit:

```dotenv
AETHER_STT_FALLBACK_MODELS=model-a,model-b
AETHER_TTS_FALLBACK_MODELS=model-a,model-b
AETHER_TTS_FALLBACK_VOICES=voice-a,voice-b
```

TTS model and voice lists must align. The worker passes these lists to the
LiveKit Inference fallback mechanism. No API key or secret is serialized into
readiness output.

## Audition command

Installation exposes:

```text
aether-voice-audition
```

Dry run is the default and makes no provider call:

```powershell
aether-voice-audition `
  --config project-docs/testing/voice-audition.example.json `
  --output C:\ProgramData\Aether\auditions\voice-001
```

Live execution must be explicit:

```powershell
aether-voice-audition `
  --config C:\ProgramData\Aether\config\voice-audition.json `
  --output C:\ProgramData\Aether\auditions\voice-001 `
  --execute-live
```

Only `env://NAME` credential references are accepted by this command. Credential
values never enter manifests, comparison sheets, or receipts.

Each sample produces:

- exact audio artifact;
- input-text SHA-256;
- audio SHA-256;
- byte length and format;
- first-audio and total latency;
- attempts and fallback path;
- error classifications;
- hash-bound synthesis receipt.

Comparison outputs:

```text
voice-comparison.json
voice-comparison.csv
voice-comparison.md
```

Founder scoring fields cover warmth, youthful-adult impression, brightness,
articulation, Indonesian naturalness, English code-switching, emotional
presence, robotic/shrill/seductive tendencies, overall score, notes, and
disposition.

## Capability gates

Source and deterministic CI can establish:

```text
voice contracts                     IMPLEMENTED
Google/OpenAI/Cartesia adapters      IMPLEMENTED
audition hashes/latency/sheets       CONFORMED
persistent provider state            WIRED/CONFORMED
Gateway cognition resilience         WIRED/CONFORMED
LiveKit fallback configuration       WIRED/CONFORMED
```

They cannot establish:

```text
live provider fallback               requires real credential/network evidence
ACTIVE                               requires installed running host evidence
FOUNDER-PROVEN                       requires Dee's acceptance
```

## Live acceptance receipt

Activation evidence must show, without secrets:

1. provider profiles and capability IDs;
2. primary attempt and normalized failure class;
3. fallback decision ID;
4. selected fallback provider;
5. exact input and output hashes;
6. persistent state before/after;
7. Gateway cognition or LiveKit turn result;
8. no duplicate action/tool execution;
9. continuity after fallback;
10. Founder disposition.

No source merge alone upgrades these states.
