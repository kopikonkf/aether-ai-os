# Unified Browser Senses

## Purpose

Use the microphone, speaker, camera, and text facilities of a Founder-owned browser while preserving Aether as the sole cognitive and governance authority.

## Reference-derived architecture

The uploaded reference list points to Friday/LiveKit, ADA, Brahma, and OmniBot examples. The server/browser split used here follows the Friday/LiveKit pattern: the server-side agent joins a realtime room while browser/mobile participants publish media. ADA and Brahma remain useful desktop-UI references; OmniBot remains a future physical-hardware pattern.

## Session authority

A trusted operator creates a browser session. The browser receives a short-lived browser token once. The durable store keeps only the token hash.

A browser session can grant:

- text;
- microphone;
- speaker;
- camera;
- screen-share.

Granting a media capability is not approval for an external business action or runtime mutation.

## Voice path

```text
microphone WebRTC track
  → LiveKit AgentSession
  → VAD and turn detection
  → STT transcript
  → Aether Gateway worker endpoint
  → canonical audio.transcript perception
  → Aether cognition, memory, governance
  → exact response text
  → LiveKit TTS
  → remote speaker track
```

The worker's custom cognition node forwards text; it does not instantiate a second LLM.

## Camera path

The camera can publish realtime video for the room, but Aether vision cognition receives bounded keyframes only. Default behavior requires an explicit “Ask what you see” action. Automatic analysis must be explicitly enabled and runs at a bounded interval.

Raw image bytes are excluded from events and durable text memory. A local keyframe reference, content hash, size, content type, prompt, and receipt are retained.

## Fallback behavior

Without LiveKit:

- typed browser conversation remains available;
- supported browsers may use native SpeechRecognition;
- responses may be spoken with speechSynthesis;
- camera keyframes still reach Aether through HTTPS;
- the system reports degraded status instead of pretending realtime production voice is active.

## Security requirements

- expose the browser UI only through HTTPS or localhost;
- require explicit user media permission;
- keep LiveKit API secret and Aether operator token server-side where possible;
- never put LiveKit API secret in browser JavaScript;
- bind browser sessions to TTL and capability lists;
- do not expose Gateway port 8000 directly to the public internet;
- keep automatic camera analysis off by default;
- use source and model cost budgets.
