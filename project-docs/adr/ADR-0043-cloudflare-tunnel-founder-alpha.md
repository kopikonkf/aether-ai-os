# ADR-0043 — Cloudflare Tunnel Edge for Founder Alpha

- **Status:** Accepted
- **Date:** 2026-07-28
- **Scope:** Real VPS bring-up of Aether OS v0.19.2
- **Feature version impact:** None; operational overlay only

## Context

The canonical v0.19.2 deployment already separates Aether Gateway, Aether Sense Worker, AionUi, and Caddy. Its shipped public-ingress topology lets Caddy terminate TLS on ports 80/443. The Founder prefers Cloudflare for DNS, public HTTPS, and operational stability.

The same release is cross-platform at the Python Core/Gateway layer, but its complete one-domain deployment implementation is Linux-first: Linux container images, Bash, systemd, and Linux-oriented Docker Compose.

## Decision

1. Run the Founder Alpha production host on **Ubuntu 24.04 LTS x86_64**.
2. Use a **remotely managed Cloudflare Tunnel** as the only public HTTP ingress.
3. Keep **Caddy as an internal HTTP path router** on port 8080; disable Caddy automatic HTTPS.
4. Do not publish container ports 80 or 443.
5. Bind the local diagnostic port 8080 only to `127.0.0.1` on the VPS.
6. Pin AionUi to `v2.1.41` and its paired AionCore backend to `v0.1.52`; build both frontend assets and the required backend bundle inside the image.
7. Pin Caddy to `2.11.3-alpine` and cloudflared to `2026.7.2` for the initial evidence run.
8. Keep browser-to-LiveKit WebRTC on the LiveKit Cloud endpoint; only Aether's browser application and token/control APIs traverse Cloudflare Tunnel.
9. Keep native Windows support as a local development and first-pulse path. A Windows production service adapter is deferred until it is an explicit product requirement.

## Runtime topology

```text
Internet
  -> Cloudflare Universal SSL / HTTPS
  -> cloudflared (outbound connector)
  -> caddy:8080 (private Docker network)
       -> aether-gateway:8000
       -> aionui-web:25808

Live media
  browser -> LiveKit Cloud -> aether-sense-worker -> aether-gateway
```

## Consequences

### Positive

- No public origin web ports are required.
- The VPS origin IP does not need to be exposed through A/AAAA records.
- Existing one-domain routing semantics remain intact.
- Cloudflare owns public certificate issuance and renewal.
- Caddy stays replaceable and narrowly scoped.
- Production builds become reproducible by pinning AionUi, AionCore, Caddy, and cloudflared.
- The AionUi container now explicitly prepares the standalone `aioncore` binary required at runtime instead of assuming it exists.

### Negative / constraints

- Cloudflare zone activation and Tunnel configuration become deployment prerequisites.
- `cloudflared` must reach Cloudflare over outbound network paths.
- LiveKit is a separate real-time dependency and is not replaced by Cloudflare Tunnel.
- A Windows Server VPS still requires a separate service/orchestration implementation and is not considered conformed by this ADR.

## Rejected alternatives

### Public Caddy TLS on the VPS

Valid, and retained in the original release, but rejected for Founder Alpha because it requires public ingress and duplicates the Founder's chosen edge layer.

### Windows Server + Docker Desktop

Rejected as the canonical production path. It does not match the shipped Linux container stack and adds unsupported or conditional virtualization dependencies.

### Remove Caddy entirely

Rejected for this bring-up. Keeping the internal router preserves the tested path contract and prevents Cloudflare route configuration from becoming coupled to every Aether service.

## Verification gates

This ADR is complete only when evidence exists for:

1. Cloudflare zone Active.
2. Tunnel Healthy.
3. Local routed health returns Gateway status.
4. Public `/health` returns Gateway status.
5. AionUi login/UI loads on the public hostname.
6. Live provider cognition completes.
7. LiveKit worker becomes ready.
8. Browser microphone turn produces a spoken response.
9. Camera keyframe produces a governed vision turn.
10. At least one runtime body passes conformance and executes a bounded receipt.
