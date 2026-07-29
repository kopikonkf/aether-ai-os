# Founder Bring-Up — Aether OS v0.19.2

## What “alive” means in this release

Aether can run as a persistent Soul/Mind service, accept text, Telegram, browser microphone, camera keyframes, and browser conversation, remember sessions, govern actions, route runtime bodies, execute missions/opportunity loops, and expose operator consoles.

Realtime production voice requires LiveKit configuration. A live model provider remains required for non-deterministic cognition.

## Local first pulse

### Windows PowerShell

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install `
  dist\aether_core-0.19.2-py3-none-any.whl `
  dist\aether_tools-0.3.0-py3-none-any.whl `
  dist\aether_gateway-0.19.2-py3-none-any.whl
python scripts\founder_bringup.py init
python scripts\founder_bringup.py doctor
python scripts\founder_bringup.py smoke
```

### Linux/macOS

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install \
  dist/aether_core-0.19.2-py3-none-any.whl \
  dist/aether_tools-0.3.0-py3-none-any.whl \
  dist/aether_gateway-0.19.2-py3-none-any.whl
python scripts/founder_bringup.py init
python scripts/founder_bringup.py doctor
python scripts/founder_bringup.py smoke
```

Expected deterministic result:

```text
status: completed
checks_completed: 13
checks_planned: 13
```

## Browser text/camera without LiveKit

Start Gateway:

```bash
python scripts/founder_bringup.py start
```

Open:

```text
http://127.0.0.1:8000/senses
```

Localhost is a secure browser context. Enter the generated operator token to issue a bounded browser session. Text, camera preview, explicit vision keyframes, and supported browser-native STT/TTS fallback are available.

## Realtime voice through LiveKit

Install optional worker dependencies:

```bash
python -m pip install 'aether-gateway[livekit]'
```

Configure `aether-core/.env`:

```dotenv
LIVEKIT_URL=wss://<project>.livekit.cloud
LIVEKIT_API_KEY=<server-side-key>
LIVEKIT_API_SECRET=<server-side-secret>
LIVEKIT_AGENT_NAME=aether-sense
AETHER_STT_MODEL=deepgram/nova-3
AETHER_STT_LANGUAGE=multi
AETHER_TTS_MODEL=cartesia/sonic-3
AETHER_TURN_DETECTOR=multilingual
```

Check readiness:

```bash
python scripts/founder_bringup.py senses
```

Start Gateway and worker in separate terminals or services:

```bash
python scripts/founder_bringup.py start
python -m aether_gateway.browser_senses.worker start
```

On a VPS, use systemd or Docker Compose instead of terminals.

## One-domain VPS

See `project-docs/deployment/VPS_ONE_DOMAIN_DEPLOYMENT.md`.

The expected daily operation is:

```text
open https://aether.example.com
  → enter AionUi
  → navigate to /#/senses or /senses
  → allow microphone/camera
  → speak, type, or show a bounded frame
```

PowerShell/Bash remains an installation and emergency administration interface, not the daily conversation UI.

## Live body and web intelligence

Runtime and crawler adapters retain their existing conformance requirements. A browser session does not grant a runtime receipt, workspace binding, public deployment, outreach, payment, or legal authority.
