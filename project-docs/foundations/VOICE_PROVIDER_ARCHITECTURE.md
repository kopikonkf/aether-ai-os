# Aether Voice Provider Architecture

Status: ACCEPTED FOUNDATION
Date: 2026-07-30
Founder: Dee

## Purpose

Aether's voice is a replaceable expression capability behind the Aether Mind, persona, memory, governance, and action system. A natural voice provider may improve presence and turn-taking, but provider quality never grants identity or execution authority.

Canonical persona target:

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

Dee retains preview, lock, veto, and fallback control.

## Current architecture truth

The LiveKit worker currently assigns these responsibilities:

```text
LiveKit Agents SDK
→ media transport
→ VAD
→ STT
→ turn handling
→ TTS

Aether Gateway
→ identity
→ cognition
→ memory
→ governance
→ tools
→ runtime routing
→ exact response text
```

The worker forwards each completed user turn to Aether Gateway and is instructed to speak the exact text returned by Aether. This authority boundary must remain true for every voice provider.

Current configurable defaults are:

```text
STT: deepgram/nova-3
TTS: cartesia/sonic-3
turn detection: multilingual
```

These defaults are configuration, not constitutional commitments.

## ChatGPT Voice versus OpenAI API

### ChatGPT Voice

ChatGPT Voice is a consumer feature inside supported ChatGPT applications and plans. Free and paid plan allowance is useful for Founder audition, product research, and interaction benchmarking.

It is not:

- an embeddable Aether backend;
- an API credential;
- transferable API quota;
- a production service identity;
- a replacement for Aether memory or governance.

ChatGPT plan limits must never be treated as Aether production capacity.

### OpenAI API voice

OpenAI API voice capabilities are separately billed and separately rate-limited. They require a dedicated API project/service-account credential reference. ChatGPT Plus does not fund or authorize API usage.

No permanent free API allowance may be assumed. Any account-specific trial credit is temporary evidence only.

## Integration modes

### Mode A — exact-text TTS provider

Recommended first OpenAI integration.

```text
microphone
→ LiveKit VAD/STT/turn handling
→ Aether Gateway cognition
→ exact Aether response text
→ OpenAI TTS
→ LiveKit audio output
```

Properties:

- Aether remains the sole cognitive authority;
- provider receives only bounded text needed for synthesis;
- straightforward comparison with Google, Cartesia, and local providers;
- provider failure can fall back without changing cognition;
- exact text and audio artifact hash can be recorded.

Initial OpenAI candidate: a supported speech-generation model through the LiveKit OpenAI TTS plugin or a thin Aether-owned adapter.

### Mode B — OpenAI STT plus separate TTS

Optional input-side provider substitution.

```text
microphone
→ OpenAI streaming/transcription STT
→ Aether Gateway cognition
→ selected TTS provider
→ audio output
```

This can improve multilingual recognition while preserving Aether-owned response generation.

### Mode C — OpenAI Realtime speech understanding with separate TTS

Possible research mode. The Realtime model may consume audio and return text while a separately selected TTS speaks the result. It requires proof that the model does not independently answer around the Aether Gateway.

### Mode D — full OpenAI Realtime speech-to-speech

Deferred optional voice-runtime/provider body.

A full realtime model naturally performs audio understanding, reasoning, turn handling, tool use, and audio generation. Using it directly as the conversational agent can create a second cognitive authority beside Aether.

It may be admitted only after an explicit conformance design proves:

- Aether identity/persona remains authoritative;
- canonical memory is retrieved and written only through Aether;
- tools and mutations still use Aether governance and Approval Inbox;
- exact tool/action receipts remain authoritative;
- provider-side conversation state is bounded and disposable;
- interruption and barge-in do not bypass pending approvals;
- no provider claim is accepted as completed action evidence;
- fallback to pipeline mode preserves continuity.

Until that proof exists, full realtime speech-to-speech is not the default Aether voice path.

## Provider portfolio

Aether should use one common voice-provider contract with candidates such as:

```text
OpenAI TTS
Google Cloud TTS
Cartesia
other conformed hosted TTS
local/open-weight TTS
legacy gTTS emergency fallback
```

Provider selection is based on:

- persona fit;
- Indonesian pronunciation and code-switching;
- latency to first audio;
- streaming support;
- interruption behavior;
- stability and rate limits;
- cost;
- data policy;
- exact voice/version pinning;
- fallback compatibility.

## Audition receipt

Every audition candidate must record:

```text
provider_id
model_id
voice_id
provider/model version or snapshot
input text hash
audio SHA-256
duration
latency to first audio
total synthesis latency
language
streaming capability
fallback result
Founder score and disposition
```

Founder scoring dimensions:

```text
warmth
perceived age
brightness
articulation
natural Indonesian
English code-switching
emotional presence
robotic tendency
shrill tendency
overly seductive tendency
```

## Recommended initial sequence

```text
provider resilience contracts
→ common voice-provider manifest and receipts
→ Google TTS samples
→ OpenAI exact-text TTS samples
→ current Cartesia sample
→ optional local/fallback sample
→ blind Founder audition
→ choose primary and fallback
→ LiveKit canary
→ interruption/latency/failure proof
→ ACTIVE
→ FOUNDER-PROVEN
```

Full OpenAI Realtime integration remains a separate later issue after the exact-text TTS path is proven.

## Non-negotiable rules

- Voice quality never grants cognitive or mutation authority.
- ChatGPT subscription credentials must not be embedded into Aether.
- API credentials remain outside model context and logs.
- Provider selection must be reversible.
- A voice provider must never rewrite the exact approved response text unless the active contract explicitly permits a bounded pronunciation transformation.
- Every fallback must preserve Aether identity and canonical conversation continuity.
