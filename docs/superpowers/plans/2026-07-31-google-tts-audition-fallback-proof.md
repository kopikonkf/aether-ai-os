# Google TTS Audition And Fallback Proof

Date: 2026-07-31
Status: source-present, host-proof pending

## Decision

Add a runtime-owned TTS audition surface under `aether-body`. Google Cloud TTS
is the preferred live provider when explicitly enabled and configured. A local
WAV proof tone is the mandatory fallback, so the voice path can always produce
an audible artifact and receipt without network or credentials.

## Runtime Routes

| Route | Purpose |
|---|---|
| `/health` | Includes `tts` provider readiness and audition directory |
| `/v1/body/conformance` | Marks Google TTS audition source-present and fallback proof available |
| `/v1/body/tts/audition` | Writes an audition audio file, metadata JSON, and body receipt |

## Environment

```bash
export AETHER_HOME=/opt/aether/home
export AETHER_TTS_LANGUAGE_CODE=id-ID
export AETHER_TTS_VOICE_NAME=id-ID-Standard-A
export AETHER_TTS_AUDIO_ENCODING=MP3
```

Fallback-only proof, no network or credential:

```bash
curl -s http://127.0.0.1:8780/v1/body/tts/audition \
  -H 'content-type: application/json' \
  -d '{"text":"Aether online. Fallback proof.","allow_external":false}'
```

Google audition on host, with explicit external permission:

```bash
export AETHER_TTS_ALLOW_EXTERNAL=true
export GOOGLE_TTS_API_KEY=<redacted>

curl -s http://127.0.0.1:8780/v1/body/tts/audition \
  -H 'content-type: application/json' \
  -d '{"text":"Aether online. Google TTS audition.","allow_external":true,"max_amount_usd":0.01}'
```

Service-account based Google Cloud client is also supported when the optional
voice dependency is installed:

```bash
pip install -e ./aether-core[voice]
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
export AETHER_TTS_ALLOW_EXTERNAL=true
```

## Evidence Files

| File | Meaning |
|---|---|
| `$AETHER_HOME/runtime/body/tts/auditions/*.mp3` | Google or gTTS audio audition |
| `$AETHER_HOME/runtime/body/tts/auditions/*.wav` | Local fallback proof tone |
| `$AETHER_HOME/runtime/body/tts/auditions/*.json` | Provider attempts, fallback flag, text fingerprint |
| `$AETHER_HOME/runtime/body/receipts.jsonl` | `tts.audition.completed` or refused proof |

## Safety

- External TTS is opt-in through `allow_external=true` and
  `AETHER_TTS_ALLOW_EXTERNAL=true`.
- External audition refuses when the mind daemon is unreachable.
- Any paid audition can pass `max_amount_usd`, which goes through the same
  budget and North Star gates as other body actions.
- The fallback WAV is an audible proof tone, not speech. It proves the audio
  artifact and receipt path when Google is unavailable.

## Status After This Slice

| Gap | Status |
|---|---|
| Google TTS provider path | Source-present |
| Google host audition | Pending credentialed host run |
| Fallback proof | Implemented with local WAV artifact and receipt |
| Telegram/LiveKit voice routing | Not wired in this slice |
| Founder-proven | Pending |
