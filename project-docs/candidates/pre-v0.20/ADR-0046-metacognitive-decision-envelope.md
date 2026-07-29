# ADR-0046 — Evidence-Bound Metacognitive Decision Envelope

Status: Accepted as the first decision-intelligence capability  
Scope: Pre-v0.20 candidate, designed for v0.20 integration

## Problem

Aether already has reflection, curiosity, predictions, failure fingerprints, governance, approvals, and experiment evidence. These systems do not yet produce one consistent answer to:

- What do I actually know?
- What is uncertain or contradictory?
- What evidence is missing or stale?
- How consequential and reversible is the action?
- Have I failed this way before?
- Should I proceed, verify, prototype, ask Dee, or block?

Asking a language model “how confident are you?” is not sufficient. Model confidence is uncalibrated and can become persuasive fiction.

## Decision

Introduce a deterministic `MetacognitiveAssessment` calculated from operational evidence:

```text
objective
+ direct observations
+ independent sources
+ contradictions
+ evidence freshness
+ prior successes/failures
+ novelty
+ reversibility
+ impact
+ external cost knowledge
+ prior failure fingerprint
-> confidence band
-> uncertainty sources
-> knowledge gaps
-> recommendation
-> human-review requirement
```

Allowed recommendations:

- `proceed`
- `verify-first`
- `prototype-small`
- `ask-founder`
- `block`

Provider-reported confidence is accepted only as weak evidence and cannot override consequence policy.

## Constitutional behavior

A high-impact action that repeats a known failure fingerprint without an explicit reason is blocked. This directly operationalizes:

> Aether must never repeat the same mistake twice without an explicit reason.

The assessor never expands execution authority. Governance remains authoritative.

## Integration path

1. Emit an assessment before external-action impact briefs.
2. Include assessment ID in mission plans, approval requests, deployment promotions, and CEE learning.
3. Escalate high-impact, irreversible, contradictory, or low-evidence work.
4. Compare predicted confidence with actual outcomes for calibration.
5. Surface the assessment through Telegram/AionUi without exposing private reasoning traces.

## Non-goals

- simulating consciousness;
- exposing chain-of-thought;
- treating model self-confidence as truth;
- replacing North Star, governance, or Founder authority;
- blocking low-risk reversible experimentation unnecessarily.
