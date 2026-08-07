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
    offenders = re.findall(r"http://127\.0\.0\.1:80(?!80|0)", combined)
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
    assert "authenticated_all_ok" in probe
    assert "AllowAutoRedirect" in probe
    assert "AuthMode" in probe
    assert '"CaddyBasic"' in probe or "'CaddyBasic'" in probe
    assert "Credential" in probe
    assert "WrongCredential" in probe
    assert "unauthenticated_all_denied" in probe
    assert "invalid_credentials_all_denied" in probe
    assert "authorization_forwarded_to_upstream" in probe
    assert "header_strip_observed" in probe
    assert "EchoRoute" in probe
    assert "WWW-Authenticate" in probe or "www_authenticate" in probe


def test_probe_uses_secret_safe_credential_surface():
    probe = _read(CLOUDFLARE_DIR / "probe-cloudflare-ingress.ps1")
    # No plaintext password parameter may exist: passwords come from a
    # PSCredential object or stdin only.
    assert "CredentialPasswordStdin" in probe
    assert "[string]$CredentialPassword" not in probe
    assert "[string]$WrongCredentialPassword" not in probe
    assert "CredentialPassword" not in re.sub(r"PasswordStdin", "", probe)
    # The header-strip conclusion must come from the echo upstream observation,
    # never from an inspection of Caddy /config/.
    assert "CaddyAdminUrl" not in probe
    assert "caddy_config_checked" not in probe
    assert ".json" in probe or "-Authorization" in probe


def test_install_writes_auth_fragment_and_never_records_hash():
    install = _read(CLOUDFLARE_DIR / "install-cloudflare-ingress.ps1")
    assert "FounderAuthFile" in install
    assert "FounderBcryptHash" not in install
    assert "founder-auth.caddy" in install
    assert 'basic_auth bcrypt "Aether Founder Alpha"' in install
    assert "auth_hash_recorded" in install
    assert r"$2[aby]$14$" in install or r"2[aby]\$14\$" in install
    assert "FounderUsername" in install


def test_caddyfile_imports_auth_fragment_and_strips_authorization():
    caddyfile = _read(ROOT / "deploy" / "windows" / "Caddyfile")
    assert "founder-auth.caddy" in caddyfile
    assert "header_up -Authorization" in caddyfile
    assert caddyfile.count("header_up -Authorization") == 4


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
    assert "Test-AetherAccessProtected" in probe
    assert ".cloudflareaccess.com" in probe
    assert "/cdn-cgi/access/" in probe
    assert "401, 403" in probe
    assert "access_protected" in probe
    assert re.search(r"unauthenticatedAllDenied.*basic_challenge", probe, re.S)


def test_install_checks_icacls_exit_code_and_acl_postcondition():
    install = _read(CLOUDFLARE_DIR / "install-cloudflare-ingress.ps1")
    assert "if ($LASTEXITCODE -ne 0)" in install
    assert "ACL hardening failed" in install
    assert "ACL postcondition verification failed" in install
    assert "AreAccessRulesProtected" in install
    assert "required_sid_missing" in install
    assert "required_rule_incomplete" in install
    assert "ContainerInherit" in install
    assert "ObjectInherit" in install
    assert "S-1-5-18" in install
    assert "S-1-5-32-544" in install
