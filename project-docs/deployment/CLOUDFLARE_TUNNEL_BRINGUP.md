# Cloudflare Tunnel Bring-Up — Aether OS v0.19.2

## 0. Resulting boundary

```text
Public hostname: https://aether.example.com
Cloudflare route service: http://caddy:8080
Host diagnostic route: http://127.0.0.1:8080
Public VPS ports: SSH only
```

Do not place API keys or the Tunnel token in source control.

## 1. Activate the domain on Cloudflare

1. Add the apex domain to Cloudflare.
2. Review imported DNS records, especially mail records.
3. If DNSSEC is enabled at the registrar, follow Cloudflare's migration precautions before changing nameservers.
4. Replace registrar nameservers with the two Cloudflare-assigned nameservers.
5. Continue only after the Cloudflare zone status is `Active`.

For a Free or Pro zone, full setup is the intended path. It makes Cloudflare authoritative for DNS.

## 2. Provision the Ubuntu VPS

Recommended initial profile:

```text
Ubuntu 24.04 LTS x86_64
4 vCPU
8 GB RAM
80 GB NVMe
```

Create a non-root sudo user and use SSH keys. Apply provider security updates before installation.

## 3. Install Docker Engine and Compose plugin

Use Docker's official Ubuntu repository. Confirm:

```bash
docker version
docker compose version
```

The Aether launcher rejects the host when these commands are absent.

## 4. Transfer and initialize the release

```bash
unzip Aether_OS_v0.19.2-cloudflare-bringup.1.zip
cd Aether_OS_v0.19.2-cloudflare-bringup.1
chmod +x START_AETHER_CLOUDFLARE.sh
./START_AETHER_CLOUDFLARE.sh init
```

This creates:

- `aether-core/.env` with generated Aether secrets;
- `deploy/cloudflare.env` from its safe example.

## 5. Configure Aether secrets locally

Edit `aether-core/.env`:

```dotenv
# Exactly one is sufficient for the first live cognition turn.
GEMINI_API_KEY=<secret>

AETHER_PUBLIC_BASE_URL=https://aether.example.com

# Required for realtime voice.
LIVEKIT_URL=wss://<project>.livekit.cloud
LIVEKIT_API_KEY=<server-side-key>
LIVEKIT_API_SECRET=<server-side-secret>
LIVEKIT_AGENT_NAME=aether-sense
```

Keep generated `AUTH_SECRET_KEY`, `AETHER_OPERATOR_TOKEN`, `AETHER_BROWSER_SENSE_SECRET`, and `AETHER_SENSE_WORKER_TOKEN` unchanged.

A live camera keyframe requires a configured multimodal-capable cognition path.

## 6. Create the Cloudflare Tunnel

In Cloudflare:

1. Create a remotely managed Tunnel named `aether-founder-alpha`.
2. Choose Docker as the connector environment.
3. Copy only the Tunnel token into `deploy/cloudflare.env`.
4. Add a Published application route:

```text
Hostname: aether.example.com
Service:  http://caddy:8080
```

The service name `caddy` resolves inside the Compose network.

Edit `deploy/cloudflare.env`:

```dotenv
AETHER_DOMAIN=aether.example.com
AIONUI_REF=v2.1.41
AIONCORE_VERSION=v0.1.52
CADDY_IMAGE=caddy:2.11.3-alpine
CLOUDFLARED_IMAGE=cloudflare/cloudflared:2026.7.2
CLOUDFLARE_TUNNEL_TOKEN=<secret-token>
```

## 7. Preflight

```bash
./START_AETHER_CLOUDFLARE.sh preflight
```

Expected terminal state:

```json
{
  "ready": true,
  "livekit_profile": true
}
```

Partial LiveKit configuration is rejected. Mutable AionUi/AionCore refs and `latest` edge image tags are rejected by default.

## 8. Start the conformed stack

```bash
./START_AETHER_CLOUDFLARE.sh up
```

The launcher automatically enables the Compose `livekit` profile when all three LiveKit credentials are present.

Inspect:

```bash
./START_AETHER_CLOUDFLARE.sh status
./START_AETHER_CLOUDFLARE.sh logs
```

## 9. Verify network and application health

```bash
./START_AETHER_CLOUDFLARE.sh verify \
  --public-base-url https://aether.example.com
```

The verifier checks:

- local Caddy-routed `/health`;
- public `/health`;
- public AionUi root;
- public `/senses` page;
- Cloudflare response headers when present.

It does not fabricate media evidence. Microphone, spoken response, and camera verification remain explicit human-in-the-loop gates.

## 10. Execute real Founder bring-up

Perform and record, in order:

1. Open `https://aether.example.com`.
2. Confirm AionUi loads and authentication works.
3. Open `/#/senses` or `/senses`.
4. Confirm live provider cognition with a text turn.
5. Confirm LiveKit worker readiness.
6. Grant microphone permission and speak one turn.
7. Confirm one audible Aether response.
8. Grant camera permission.
9. Submit exactly one explicit keyframe.
10. Confirm raw audio/image payloads are not written to text-memory/event paths.
11. Bind and execute one conformed runtime body.
12. Save logs and the completed evidence record.

Use `project-docs/deployment/BRINGUP_EVIDENCE_TEMPLATE.md` as the canonical record.

## 11. Operations

```bash
./START_AETHER_CLOUDFLARE.sh status
./START_AETHER_CLOUDFLARE.sh logs
./START_AETHER_CLOUDFLARE.sh down
```

Do not delete Docker volumes during routine restart. Before upgrades, back up the `aether-data` and `aionui-data` volumes.
