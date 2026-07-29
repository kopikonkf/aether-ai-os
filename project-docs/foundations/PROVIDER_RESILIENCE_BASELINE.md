# Aether Provider Resilience Baseline

Status: IMPLEMENTED FOUNDATION, NOT YET RUNTIME-WIRED

Date: 2026-07-30

Founder: Dee

## Purpose

Aether must not let a single provider outage, quota exhaustion, billing condition, malformed request, or transient network failure silently stall the Mind or create uncontrolled retry storms.

This baseline defines provider-neutral contracts for:

- failure classification;
- bounded retry and backoff;
- daily request budgets;
- concurrency budgets;
- provider cooldown;
- circuit breakers;
- capability-aware fallback selection;
- hash-bound decision and circuit receipts.

The contracts contain no credentials and make no live network calls.

## Error taxonomy

A provider failure is normalized into one of:

```text
rate_limit
quota_exhausted
server_transient
network_transient
authentication
invalid_request
unsupported
unknown
```

### 429 distinction

Aether must distinguish:

```text
429 rate_limit
→ bounded retry may be appropriate
→ honor Retry-After
→ cooldown may apply

429 quota_exhausted
→ do not retry blindly
→ mark current provider/model unavailable for the budget window
→ evaluate an approved fallback
→ surface Founder-visible billing/quota evidence
```

Quota/billing markers include provider-specific codes such as `insufficient_quota`, hard billing limits, exhausted credits, daily/RPD limits, or spend-limit messages.

Unknown 429 responses default to rate-limit classification rather than inventing a billing condition.

## Retry policy

Retry is allowed only for:

- rate limiting;
- transient server failures;
- transient network failures.

Retry is not automatic for:

- quota/billing exhaustion;
- authentication failures;
- invalid requests;
- unsupported endpoints/models/capabilities;
- unknown failures.

The policy uses:

```text
bounded exponential delay
+ deterministic jitter
+ Retry-After floor
+ absolute maximum delay
+ explicit maximum attempt count
```

Failed attempts must not loop without bound. Provider adapters remain responsible for mapping native error objects into the provider-neutral signal.

## Daily request budget

Every provider profile may declare a daily request limit.

For the current Aether starting point:

```text
Aether primary cognition profile
→ 100 requests/day
```

The budget:

- fails closed when exhausted;
- resets only when the declared day key changes;
- does not infer capacity from the number of API keys;
- must later be persisted through an AETHER_HOME-owned service/store;
- must be attributable by provider, model, capability, and workload lane.

The current implementation is an in-memory contract. Runtime persistence is deferred to Gateway wiring.

## Concurrency budget

Concurrency is controlled independently from daily volume.

A provider may have remaining daily capacity while still being temporarily unavailable because all allowed concurrent slots are occupied.

The contract:

- acquires before dispatch;
- rejects dispatch at the declared limit;
- releases exactly once after completion/failure;
- rejects underflow;
- remains separate per provider/profile/capability lane.

## Circuit breaker

Circuit states:

```text
closed
→ normal traffic

open
→ requests blocked during cooldown

half_open
→ one bounded probe permitted
```

The breaker opens after the configured failure threshold, or after a failed half-open probe.

Invalid-request and unknown errors do not automatically poison provider health because they may be workload-specific rather than evidence that the provider is unavailable.

Circuit receipts are SHA-256 bound to:

- provider ID;
- state;
- consecutive failure count;
- opened time;
- observed time;
- cooldown;
- reason.

## Fallback eligibility matrix

Fallback is not based on provider order alone.

Each candidate must satisfy:

- enabled state;
- health state;
- required capabilities;
- remaining daily budget;
- available concurrency;
- circuit state;
- cooldown expiry;
- allowed data-policy tags.

The selection is deterministic by priority and stable provider ID. Every candidate receives explicit eligibility or rejection reasons, and the complete decision receives a SHA-256 decision ID.

## Voice portfolio example

Founder-preferred initial TTS order:

```text
Primary candidates
1. google-cloud-tts
2. openai-exact-tts
3. cartesia

Fallback candidates
4. other conformed hosted provider
5. local/open-weight TTS
6. gTTS emergency fallback
```

The example order never overrides capability, health, budget, circuit, cooldown, or data-policy eligibility.

OpenAI exact-text TTS and OpenAI STT remain separately billed API capabilities. ChatGPT Voice plan allowance is not a provider budget and must never enter this matrix.

## Runtime wiring still required

This baseline does not yet:

- wrap current cognition providers;
- wrap LiveKit STT/TTS providers;
- persist budgets or breaker state;
- emit events through the Gateway event bus;
- expose operator status through API/AionUi/CLI;
- perform live fallback;
- manage credential references;
- prove behavior under real provider failures.

Required next wiring:

```text
provider-native error adapter
→ ProviderErrorSignal
→ retry/budget/circuit evaluation
→ capability-aware fallback decision
→ provider call
→ receipt/event persistence
→ operator projection
```

## Capability truth

```text
error taxonomy                    IMPLEMENTED
429 rate/quota distinction        IMPLEMENTED
retry/backoff contract            IMPLEMENTED
daily request budget contract     IMPLEMENTED
concurrency budget contract       IMPLEMENTED
circuit-breaker contract          IMPLEMENTED
fallback eligibility matrix       IMPLEMENTED
hash-bound receipts               IMPLEMENTED
unit conformance                  CONFORMED
Gateway provider wiring           NOT WIRED
LiveKit voice-provider wiring     NOT WIRED
persistent AETHER_HOME state      NOT IMPLEMENTED
ACTIVE                            NO
FOUNDER-PROVEN                    NO
```
