# VPS One-Domain Deployment

## Recommended Founder Alpha host

```text
Ubuntu 24.04 LTS x86_64
4 vCPU
8 GB RAM
80 GB NVMe
4 GB swap
public IPv4
Jakarta or Singapore region after latency comparison
```

GPU is not required while model, STT, TTS, and vision inference use external providers.

## DNS and TLS

Point the chosen domain to the VPS public IPv4. Caddy obtains and renews TLS certificates. Only ports 80 and 443 should be public. Restrict SSH using a firewall, fixed source IP, or a private overlay network.

Do not expose ports 8000 and 25808 directly.

## Docker Compose path

1. Install Docker Engine and the Compose plugin.
2. Extract this release.
3. Initialize Aether secrets:

```bash
python3 scripts/founder_bringup.py init
```

4. Configure `aether-core/.env`:

```dotenv
HOST=0.0.0.0
PORT=8000
AETHER_PUBLIC_BASE_URL=https://aether.example.com
LIVEKIT_URL=wss://<project>.livekit.cloud
LIVEKIT_API_KEY=<server-side-key>
LIVEKIT_API_SECRET=<server-side-secret>
```

5. Configure the public domain:

```bash
cp deploy/.env.example deploy/.env
# edit AETHER_DOMAIN
```

6. Start:

```bash
./START_AETHER_ONE_DOMAIN.sh
```

The AionUi image is built from the selected upstream ref, then the Aether integration installer adds the `/senses` route. This build requires internet access and has not been executed in the offline release container.

## Windows service path

Windows VPS service source lives under deploy/windows/.

Run from an elevated PowerShell in the immutable release root:

    .\deploy\windows\install-aether-services.ps1 -Start

The installer uses Windows Service Control Manager recovery plus an AetherWatchdog service. It sets the service-owned runtime state explicitly to C:\ProgramData\Aether, keeps release files immutable under C:\Aether\releases\..., and writes secret-safe heartbeat receipts to C:\ProgramData\Aether\services\heartbeats.jsonl.

Required Windows checks before classifying the service slice beyond source-level:

    Get-Service AetherGateway,AetherWatchdog
    Invoke-RestMethod http://127.0.0.1:8000/health
    Get-Content C:\ProgramData\Aether\services\heartbeats.jsonl -Tail 3

Do not expose port 8000 publicly. Public ingress remains a separate Cloudflare/Caddy step.

## systemd path

Use deploy/scripts/install_vps.sh for the Aether virtual environment and base units. Review /etc/aether/aether.env before starting services.

```bash
sudo deploy/scripts/install_vps.sh "$PWD"
sudo systemctl start aether-gateway
sudo systemctl enable --now aether-sense-worker  # only after LiveKit installation/configuration
```

Build and install AionUi separately at `/opt/aionui`, then install `aionui-web.service`. Add `deploy/systemd/caddy-aether.conf` to the Caddy configuration after replacing the example domain.

## Health checks

```text
https://aether.example.com/health
https://aether.example.com/aether/api/status
https://aether.example.com/senses
https://aether.example.com/#/senses
```

## Failure isolation

- AionUi failure does not erase Aether memory or stop Telegram.
- LiveKit worker failure degrades browser voice to text/fallback.
- runtime CLI failure does not stop cognition.
- Aether Gateway failure makes the UI report the sidecar unavailable.
- Caddy owns TLS and public ingress, not Aether.
