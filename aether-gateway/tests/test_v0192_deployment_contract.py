from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_unified_browser_console_keeps_media_in_browser_transport() -> None:
    console = ROOT / "aether-gateway" / "src" / "aether_gateway" / "aionui_senses_console"
    html = (console / "index.html").read_text(encoding="utf-8")
    js = (console / "app.js").read_text(encoding="utf-8")
    assert "microphone" in html.lower()
    assert "camera" in html.lower()
    assert "localStorage" not in js
    assert "/api/browser-senses/session" in js
    assert "getUserMedia" in js
    assert "livekit-client@2.17.2" in js


def test_livekit_worker_delegates_cognition_to_gateway() -> None:
    worker = (ROOT / "aether-gateway" / "src" / "aether_gateway" / "browser_senses" / "worker.py").read_text(encoding="utf-8")
    assert "/api/browser-senses/worker/chat" in worker
    assert "Aether Gateway is the only cognitive authority" in worker
    assert "openai" not in worker.lower()
    assert "anthropic" not in worker.lower()


def test_one_domain_deployment_routes_senses_to_aether_and_root_to_aionui() -> None:
    caddy = (ROOT / "deploy" / "caddy" / "Caddyfile").read_text(encoding="utf-8")
    compose = (ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")
    assert "/api/browser-senses" in caddy
    assert "reverse_proxy aether-gateway:8000" in caddy
    assert "reverse_proxy aionui-web:25808" in caddy
    for service in ("aether-gateway", "aether-sense-worker", "aionui-web", "caddy"):
        assert service in compose


def test_systemd_services_keep_aether_and_aionui_as_separate_processes() -> None:
    gateway = (ROOT / "deploy" / "systemd" / "aether-gateway.service").read_text(encoding="utf-8")
    worker = (ROOT / "deploy" / "systemd" / "aether-sense-worker.service").read_text(encoding="utf-8")
    aionui = (ROOT / "deploy" / "systemd" / "aionui-web.service").read_text(encoding="utf-8")
    assert "ExecStart=/opt/aether/.venv/bin/aether-gateway" in gateway
    assert "ExecStart=/opt/aether/.venv/bin/aether-sense-worker start" in worker
    assert "ExecStart=/usr/local/bin/bun run webui:prod:remote" in aionui


def test_aionui_pack_contains_native_route_and_non_destructive_installer() -> None:
    page = ROOT / "aionui-integration" / "packages" / "desktop" / "src" / "renderer" / "pages" / "unified-senses" / "index.tsx"
    installer = (ROOT / "aionui-integration" / "scripts" / "install_aionui_integration.py").read_text(encoding="utf-8")
    assert page.is_file()
    assert "src={sensesUrl}" in page.read_text(encoding="utf-8")
    assert "--wire-router" in installer
    assert "refusing unsafe automatic patch" in installer.lower()


def test_windows_status_uses_portable_os_fallbacks() -> None:
    script = (ROOT / "START_AETHER_WINDOWS_ALPHA.ps1").read_text(encoding="utf-8")
    assert "function Get-PortableOSDescription" in script
    assert "Get-CimInstance -ClassName Win32_OperatingSystem" in script
    assert "[Environment]::OSVersion.VersionString" in script
    assert "function Get-PortableOSArchitecture" in script
    assert "[Environment]::Is64BitOperatingSystem" in script
    assert "os = Get-PortableOSDescription" in script
    assert "architecture = Get-PortableOSArchitecture" in script

    readiness = (ROOT / "AETHER_WINDOWS_READINESS.ps1").read_text(encoding="utf-8")
    assert "function Get-PortableRuntimeArchitecture" in readiness
    assert "$runtimeArchitecture = Get-PortableRuntimeArchitecture" in readiness
    assert "RuntimeInformation]::OSArchitecture.ToString()" not in readiness


def test_state_inspector_v2_covers_active_authorities_and_legacy_boundary() -> None:
    script = (ROOT / "scripts" / "aether_state_continuity.py").read_text(encoding="utf-8")
    assert '"aether.state-continuity.audit.v2"' in script
    for token in (
        "fleet-operations.sqlite3",
        "opportunity-intelligence.sqlite3",
        "live-web-intelligence.sqlite3",
        "reversible-experiments.sqlite3",
        "browser-senses.sqlite3",
    ):
        assert token in script
    assert 'home / "legacy" / "archives" / "original-brain"' in script
    assert '"automatic_imports_authorized": 0' in script
