from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WINDOWS_DIR = ROOT / "deploy" / "windows"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_windows_service_assets_are_present():
    required = [
        "README.md",
        "install-aether-services.ps1",
        "uninstall-aether-services.ps1",
        "aether-service-runner.ps1",
        "aether-watchdog.ps1",
    ]
    missing = [name for name in required if not (WINDOWS_DIR / name).is_file()]
    assert missing == []


def test_windows_service_assets_bind_runtime_state_and_heartbeat_receipts():
    combined = "\n".join(_read(path) for path in WINDOWS_DIR.iterdir() if path.is_file())
    assert r"C:\ProgramData\Aether" in combined
    assert "AetherGateway" in combined
    assert "AetherWatchdog" in combined
    assert "heartbeats.jsonl" in combined
    assert "service-events.jsonl" in combined
    assert "http://127.0.0.1:8000/health" in combined
    assert "Restart-Service -Name \"AetherGateway\"" in combined


def test_gateway_exposes_cheap_health_endpoint_for_watchdog():
    server = _read(ROOT / "aether-gateway" / "src" / "aether_gateway" / "api" / "server.py")
    assert '@app.get("/health")' in server
    assert '"service": "aether-gateway"' in server
    health_block = server.split('@app.get("/health")', 1)[1].split('@app.get("/api/status")', 1)[0]
    assert "memory_fabric.stats()" not in health_block


def test_windows_service_assets_do_not_embed_secrets_or_legacy_state_paths():
    combined = "\n".join(_read(path) for path in WINDOWS_DIR.iterdir() if path.is_file())
    prohibited = [
        "TELEGRAM_BOT_TOKEN=",
        "LIVEKIT_API_SECRET=",
        "AUTH_SECRET_KEY=",
        r"C:\aether\aether-home",
        "HERMES_HOME",
    ]
    offenders = [item for item in prohibited if item in combined]
    assert offenders == []