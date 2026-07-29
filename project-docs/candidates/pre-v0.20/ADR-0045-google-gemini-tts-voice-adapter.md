# ADR-0045 — Google Gemini TTS as a Replaceable Aether Voice Adapter

Status: Accepted as a pre-v0.20 implementation candidate  
Authority boundary: Senses / expression adapter only

## Context

Aether's identity, cognition, memory, governance, and runtime routing must remain provider-independent. Voice synthesis converts already-decided spoken text into audio. It must never become Aether's mind, identity, or authority.

The legacy `[VOICE]...[/VOICE]` markup was an implementation hint from an earlier agent workflow. It must remain backward compatible, but it cannot remain the mandatory interface for speaking.

## Decision

1. Introduce a provider-neutral speech-rendering boundary.
2. Use Gemini Developer API TTS as the preferred Founder-alpha provider while its free tier is available.
3. Do not encode “free” or “unlimited” as an architectural guarantee.
4. Preserve fallback order:
   - Google Gemini TTS;
   - browser/native speech synthesis or future local TTS adapter;
   - text-only delivery.
5. Treat `[VOICE]` as an optional legacy authoring hint, not a required gate.
6. Aether may choose a voice from a Founder-approved portfolio based on conversational mode and delivery intent.
7. Dee may preview, rate, lock, disable, or veto any voice.
8. Voice choice changes expression, not identity.
9. Persist voice-selection reasons and outcomes without storing sensitive transcript content.

## Voice autonomy

Aether's autonomy is bounded, not fake randomness:

```text
approved portfolio
  + interaction mode
  + emotional delivery intent
  + Aether affinity
  + Founder feedback
  -> selected voice + reason
```

The initial audition portfolio includes Aoede, Leda, Achernar, Vindemiatrix, Sulafat, Laomedeia, Autonoe, and Despina. Provider documentation describes tonal traits, not gender; the actual voice must be auditioned.

## Language behavior

- Indonesian is the default semantic language.
- Natural Indonesian-English code-switching is allowed.
- Avoid textbook translation and forced slang.
- Style and delivery instructions may be passed as natural-language director notes.

## Privacy and cost boundary

Gemini Developer API free-tier traffic may be used by Google to improve products. Sensitive or governed content must therefore be routed according to data policy, potentially to a paid/no-training tier or a local adapter. Google Cloud Text-to-Speech is a separate billed product and must not be confused with the Gemini Developer API free tier.

## Consequences

- Aether gains provider-quality, controllable speech without identity coupling.
- Free-tier availability reduces Founder-alpha cost but does not remove quota monitoring.
- Provider outages or policy changes do not silence Aether because fallbacks remain available.
