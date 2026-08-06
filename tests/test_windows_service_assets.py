from __future__ import annotations

import os
from pathlib import Path
import runpy
import shutil
import subprocess

import pytest


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
        "aether-windows-service.py",
    ]
    missing = [name for name in required if not (WINDOWS_DIR / name).is_file()]
    assert missing == []


def test_windows_service_installer_delimits_last_exit_code_before_colon():
    installer = _read(WINDOWS_DIR / "install-aether-services.ps1")

    assert "$LASTEXITCODE:" not in installer
    assert "${LASTEXITCODE}:" in installer


def test_powershell_assets_parse(tmp_path: Path):
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        if os.environ.get("CI"):
            pytest.fail("PowerShell is required to parse-check repository .ps1 assets in CI")
        pytest.skip("PowerShell is unavailable in this local environment")

    validator = tmp_path / "parse-powershell-assets.ps1"
    validator.write_text(
        """[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RepositoryRoot
)

$parseFailures = @()
$scripts = Get-ChildItem -LiteralPath $RepositoryRoot -Filter "*.ps1" -File -Recurse
foreach ($script in $scripts) {
    $tokens = $null
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile(
        $script.FullName,
        [ref]$tokens,
        [ref]$errors
    ) | Out-Null

    foreach ($parseError in $errors) {
        $parseFailures += "{0}:{1}:{2}: {3}" -f @(
            $script.FullName,
            $parseError.Extent.StartLineNumber,
            $parseError.Extent.StartColumnNumber,
            $parseError.Message
        )
    }
}

if ($parseFailures.Count -gt 0) {
    $parseFailures | Write-Error
    exit 1
}
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(validator),
            "-RepositoryRoot",
            str(ROOT),
        ],
        capture_output=True,
        check=False,
        text=True,
        timeout=60,
    )

    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    assert result.returncode == 0, output


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


def test_service_binary_uses_an_scm_dispatcher_host():
    installer = _read(WINDOWS_DIR / "install-aether-services.ps1")
    host = _read(WINDOWS_DIR / "aether-windows-service.py")

    assert "$serviceHost = Join-Path" in installer
    assert "New-ServiceHostCommand" in installer
    assert "$gatewayBin = New-ServiceHostCommand" in installer
    assert "$watchdogBin = New-ServiceHostCommand" in installer
    assert "Join-ServiceCommand $powerShellExe" not in installer
    assert "StartServiceCtrlDispatcherW" in host
    assert "RegisterServiceCtrlHandlerExW" in host
    assert "SetServiceStatus" in host
    assert "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE" in host


def test_watchdog_is_independent_and_existing_dependencies_are_normalized():
    installer = _read(WINDOWS_DIR / "install-aether-services.ps1")
    watchdog_install = next(
        line
        for line in installer.splitlines()
        if line.startswith('Install-OrUpdate-Service -Name "AetherWatchdog"')
    )

    assert "-DependsOn" not in watchdog_install
    assert '"depend=", $dependencyValue' in installer
    assert 'Invoke-ServiceControl -Arguments @("failureflag", $Name, "1")' in installer


def test_service_host_argument_boundary_preserves_child_argv():
    namespace = runpy.run_path(str(WINDOWS_DIR / "aether-windows-service.py"))
    parse_args = namespace["_parse_args"]
    args = parse_args(
        [
            "--service-name",
            "AetherGateway",
            "--working-directory",
            r"C:\Aether\releases\abc",
            "--event-log-path",
            r"C:\ProgramData\Aether\services\service-events.jsonl",
            "--",
            r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
            "-NoProfile",
            "-File",
            r"C:\Aether\releases\abc\deploy\windows\aether-service-runner.ps1",
        ]
    )

    assert args.service_name == "AetherGateway"
    assert args.command[0].lower().endswith("powershell.exe")
    assert args.command[1:] == [
        "-NoProfile",
        "-File",
        r"C:\Aether\releases\abc\deploy\windows\aether-service-runner.ps1",
    ]
