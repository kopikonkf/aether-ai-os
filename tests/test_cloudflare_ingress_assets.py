from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLOUDFLARE_DIR = ROOT / "deploy" / "cloudflare"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_cloudflare_ingress_assets_are_present():
    required = [
        "README.md",
        "cloudflared-aether.yml",
        "install-cloudflare-ingress.ps1",
        "probe-cloudflare-ingress.ps1",
    ]
    missing = [name for name in required if not (CLOUDFLARE_DIR / name).is_file()]
    assert missing == []


def test_cloudflare_ingress_assets_bind_one_domain_routes_and_receipts():
    combined = "\n".join(_read(path) for path in CLOUDFLARE_DIR.iterdir() if path.is_file())
    assert "AetherCloudflareTunnel" in combined
    assert "http://127.0.0.1:80" in combined
    assert "/health" in combined
    assert "/aether/api/status" in combined
    assert "/api/browser-senses/status" in combined
    assert "/senses" in combined
    assert "latest_cloudflare_probe.json" in combined
    assert "cloudflare-probes.jsonl" in combined


def test_cloudflare_ingress_assets_do_not_embed_secrets_or_direct_gateway_exposure():
    combined = "\n".join(_read(path) for path in CLOUDFLARE_DIR.iterdir() if path.is_file())
    prohibited = [
        "CLOUDFLARE_TUNNEL_TOKEN=",
        "LIVEKIT_API_SECRET=",
        "AUTH_SECRET_KEY=",
        "TELEGRAM_BOT_TOKEN=",
        "0.0.0.0:8000",
        "HERMES_HOME",
    ]
    offenders = [item for item in prohibited if item in combined]
    assert offenders == []
