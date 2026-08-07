from __future__ import annotations

import re
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
    assert "http://127.0.0.1:8080" in combined
    assert "/health" in combined
    assert "/aether/api/status" in combined
    assert "/api/browser-senses/status" in combined
    assert "/senses" in combined
    assert "latest_cloudflare_probe.json" in combined
    assert "cloudflare-probes.jsonl" in combined


def test_cloudflare_ingress_assets_do_not_use_plain_http_origin_on_port_80():
    combined = "\n".join(_read(path) for path in CLOUDFLARE_DIR.iterdir() if path.is_file())
    import re
    offenders = re.findall(r"http://127\.0\.0\.1:80(?!80)", combined)
    assert offenders == []


def test_cloudflare_ingress_assets_install_aethercaddy_and_tunnel():
    install = _read(CLOUDFLARE_DIR / "install-cloudflare-ingress.ps1")
    assert "AetherCaddy" in install
    assert "New-Service -Name $caddyServiceName" in install
    assert "$CaddyPath validate --config" in install
    assert "AetherCloudflareTunnel" in install


def test_cloudflare_ingress_probe_supports_access_enforcement_and_authenticated_modes():
    probe = _read(CLOUDFLARE_DIR / "probe-cloudflare-ingress.ps1")
    assert "AccessCookie" in probe
    assert "ExpectAccessEnforcement" in probe
    assert "CF_Authorization" in probe
    assert "unauthenticated_all_protected" in probe
    assert "authenticated_all_ok" in probe
    assert "-MaximumRedirection 0" in probe


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


def test_probe_access_protection_covers_redirect_and_denial():
    probe = _read(CLOUDFLARE_DIR / "probe-cloudflare-ingress.ps1")
    assert "(300 -and" in probe or "$statusCode -le 399" in probe
    assert "401, 403" in probe
    assert "access_protected" in probe
    assert "access_protected" in probe  # used in post-processing
    assert re.search(r"unauthenticatedAllProtected.*access_protected", probe, re.S)


def test_install_checks_icacls_exit_code_and_acl_postcondition():
    install = _read(CLOUDFLARE_DIR / "install-cloudflare-ingress.ps1")
    assert "if ($LASTEXITCODE -ne 0)" in install
    assert "ACL hardening failed" in install
    assert "ACL postcondition verification failed" in install
    assert "AreAccessRulesProtected" in install
    assert "S-1-5-18" in install
    assert "S-1-5-32-544" in install
