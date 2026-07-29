# Aether OS v0.19.2 — Founder Alpha Frozen.1

> **Start here:** `START_HERE_CONSOLIDATED.md`  
> **Build ID:** `v0.19.2-founder-alpha-frozen.1`

This folder is the frozen Windows-laptop baseline. It supersedes all earlier sliced overlays and consolidated candidates. Mutable state remains external under `AETHER_HOME`.

Aether v0.19.2 turns the Founder alpha into a browser-operable system. A phone or laptop supplies microphone, speaker, camera, text, and optional screen media; Aether remains the identity, cognition, memory, governance, mission, opportunity, and runtime authority.

```text
Chrome / Android / Laptop
  → HTTPS browser permissions
  → LiveKit WebRTC or bounded browser fallback
  → Aether Sense Worker
  → Aether Gateway
  → cognition / memory / governance / body
  → TTS or browser expression
  → user speaker and screen
```

## Process topology

Aether is not compiled into the AionUi mind. The deployment is a hybrid sidecar:

```text
AionUi WebUI process       → primary operator shell
Aether Gateway process     → Soul, Mind, memory, governance, APIs
LiveKit Sense Worker       → realtime STT / VAD / turn / TTS transport
Runtime and crawler workers→ replaceable Body components
Caddy                      → one HTTPS domain
```

The user sees one domain. The operating system still supervises independent, replaceable processes.

## Unified Browser Senses

Implemented browser capabilities:

- typed text to canonical Aether sense path;
- microphone and remote speaker through LiveKit when configured;
- browser-native SpeechRecognition and speechSynthesis fallback;
- local camera preview and optional LiveKit camera publication;
- explicit or bounded-opt-in JPEG keyframe vision;
- append-only browser session, media-track, frame, and turn receipts;
- raw audio and image redaction from event and memory logs;
- short-lived browser session token, with only its SHA-256 hash stored;
- explicit HTTPS and permission requirements.

Embedded route:

```text
https://<domain>/senses
```

AionUi native route after integration wiring:

```text
https://<domain>/#/senses
```

## LiveKit boundary

LiveKit owns realtime media transport, VAD, STT, turn detection, and TTS. Its custom `llm_node` does not answer independently. It sends every completed transcript to:

```text
POST /api/browser-senses/worker/chat
```

Aether Gateway returns the exact response to speak. Missing LiveKit packages or credentials degrade to browser text and browser-native speech without blocking Aether boot.

## Vision boundary

Camera streaming and cognition are separated:

```text
continuous local/browser video
  → explicit capture or 15-second bounded opt-in
  → compressed keyframe
  → content hash and bounded local reference
  → provider-neutral vision request
  → text expression
```

The periodic analysis toggle is off by default. Providers that do not support multimodal input cannot execute the vision turn, but the browser session remains available.

## One-domain deployment

Caddy routes:

```text
/                         → AionUi WebUI
/senses*                  → Aether Gateway browser console
/api/browser-senses*      → Aether Gateway sense API
/aether/*                 → remaining Aether operator/API surfaces
/health                    → Aether Gateway status
```

Deployment options:

- Docker Compose: `deploy/docker-compose.yml`;
- systemd units under `deploy/systemd/`;
- cross-platform local supervisor: `scripts/aether_sidecar.py`.

## Founder bring-up

```bash
python scripts/founder_bringup.py init
python scripts/founder_bringup.py doctor
python scripts/founder_bringup.py smoke
python scripts/founder_bringup.py senses
```

The deterministic first pulse runs 13 checks without consuming a model key.

Start Gateway only:

```bash
python scripts/founder_bringup.py start
```

Start the local sidecar supervisor:

```bash
./START_AETHER_SIDECAR.sh --aionui-command "bun run webui:prod:remote"
```

Start the one-domain Docker stack after configuring the deployment files:

```bash
cp deploy/.env.example deploy/.env
./START_AETHER_ONE_DOMAIN.sh
```

## AionUi integration

```bash
python aionui-integration/scripts/install_aionui_integration.py /path/to/AionUi --wire-router
```

The installer:

- validates AionUi major version 2;
- copies Aether feature pages without overwriting by default;
- patches only known Router anchors when `--wire-router` is requested;
- refuses unsafe automatic modification when upstream layout changed;
- leaves sidebar styling and full upstream build verification explicit.

## Verification

Consolidated build verification:

```text
Aether Core full suite:                       147 passed
Aether Tools full suite:                       49 passed, 1 skipped
Gateway approval/provider regression slice:    7 passed
Gateway browser/deployment regression slice:  12 passed
Python/JavaScript/config syntax:               passed
Three wheels rebuilt and import-smoked:        passed
```

The original v0.19.2 baseline reported 84 Gateway tests. A fresh single-run full Gateway suite is not claimed for the consolidated build because pre-existing long-lived process/lifespan tests did not complete under this Linux build container. Modified Gateway surfaces were explicitly exercised and passed. See `project-docs/CONSOLIDATED_VERIFICATION.md`.

## Live truth

The implementation is live-capable, but this build environment did not contain LiveKit credentials or LiveKit Python packages. Therefore no real microphone-to-STT-to-Aether-to-TTS network session is claimed. Browser text, deterministic sense sessions, camera-frame contracts, API routes, UI assets, and process topology were executed locally.

See:

- `project-docs/browser-senses/UNIFIED_BROWSER_SENSES.md`
- `project-docs/deployment/VPS_ONE_DOMAIN_DEPLOYMENT.md`
- `FOUNDER_BRINGUP.md`
- `LASTSTANDINGPOINT.md`
