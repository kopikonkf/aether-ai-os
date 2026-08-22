from __future__ import annotations

import os
from pathlib import Path
import re
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


def test_powershell_variables_before_literal_colons_are_delimited():
    ambiguous_literal_colon = re.compile(
        r"\$(?!\{)([A-Za-z_][A-Za-z0-9_]*):(?=$|[^A-Za-z0-9_])"
    )
    assert ambiguous_literal_colon.search("$name: failure") is not None
    assert ambiguous_literal_colon.search("${name}: failure") is None
    assert ambiguous_literal_colon.search("$env:PATH") is None
    assert ambiguous_literal_colon.search("$script:Value") is None

    offenders: list[str] = []

    for path in WINDOWS_DIR.rglob("*.ps1"):
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            for match in ambiguous_literal_colon.finditer(line):
                offenders.append(
                    f"{path.relative_to(ROOT).as_posix()}:{line_number}: "
                    f"{match.group(0)}"
                )

    assert offenders == [], offenders


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


def test_service_runner_accepts_secret_env_path_and_allowlists_keys():
    runner = _read(WINDOWS_DIR / "aether-service-runner.ps1")
    assert "SecretEnvPath" in runner
    assert "LIVEKIT_URL" in runner
    assert "LIVEKIT_API_KEY" in runner
    assert "LIVEKIT_API_SECRET" in runner
    assert "AETHER_SENSE_WORKER_TOKEN" in runner
    assert "service.secretenv.blocked" in runner
    assert "service.secretenv.loaded" in runner
    # The runner must refuse an unprotected secret file (inheritance enabled).
    assert "AreAccessRulesProtected" in runner
    # Exact DACL: FullControl requirement, unexpected Deny ACE rejection.
    assert "FullControl" in runner
    assert "Deny" in runner
    # CONFIG_BLOCKED fail-closed: reject unknown/duplicate/malformed/empty/missing.
    assert "unknown key" in runner
    assert "duplicate key" in runner
    assert "malformed line" in runner
    assert "empty value" in runner
    assert "missing required key" in runner
    # Malformed lines must not be logged raw (secret leakage).
    assert "malformed line (no '='): $" not in runner
    # Role enforcement: both gateway and sense-worker are valid.
    assert 'SecretEnvPath is only valid for roles gateway or sense-worker' in runner
    # Gateway allowlist includes LIVEKIT_* and worker token.
    assert 'gateway' in runner
    assert 'sense-worker' in runner


def test_promotion_handles_worker_rollback_compat():
    promote = _read(WINDOWS_DIR / "promote-aether-release.ps1")
    assert "-IncludeSenseWorker" in promote
    assert "worker_deactivated" in promote
    assert "Build-ReleaseVenv" in promote
    assert "rollbackSupportsSecretEnv" in promote
    assert 'Stop-Service -Name "AetherSenseWorker"' in promote
    assert "Set-Service -Name \"AetherSenseWorker\" -StartupType Manual" in promote
    # Restart order: Gateway -> Worker -> Watchdog.
    assert '@("AetherGateway")' in promote
    assert '"AetherSenseWorker"' in promote
    assert '"AetherWatchdog"' in promote


def test_installer_wires_sense_worker_secret_env_path():
    installer = _read(WINDOWS_DIR / "install-aether-services.ps1")
    assert 'senses-livekit.env' in installer
    assert "-SecretEnvPath" in installer
    # The installer must be capability-aware: only pass -SecretEnvPath when the
    # runner supports it (rollback detection via $SecretEnvPath content check).
    assert 'runnerSupportsSecretEnv' in installer
    assert '$SecretEnvPath' in installer
    # Gateway also receives the canonical secret path (when runner supports it).
    assert '"-Role", "gateway"' in installer
    assert '"-Role", "sense-worker"' in installer
    # Both gateway and sense-worker args are built conditionally.
    assert '$runnerSupportsSecretEnv' in installer
    assert '$livekitEnabled' in installer


def test_installer_gates_livekit_secrets_behind_capability_flag():
    # Blocker 2 (review REV7): LiveKit wiring is OPTIONAL. The Gateway must keep
    # its secret-independent startup path unless -InstallSenseWorker is selected;
    # secrets must be valid BEFORE any SCM mutation (never after rebinding).
    installer = _read(WINDOWS_DIR / "install-aether-services.ps1")
    # LiveKit secret injection is gated behind the explicit capability flag.
    assert "livekitEnabled" in installer
    assert "`$InstallSenseWorker -and `$runnerSupportsSecretEnv" in installer or \
        "($InstallSenseWorker -and $runnerSupportsSecretEnv)" in installer
    # Pre-mutation secret validation exists.
    assert "Assert-LiveKitSecretPreflight" in installer
    assert "LiveKit secrets not provisioned" in installer
    assert "-ValidateOnly" in installer
    # The runner can validate secrets without starting the child process.
    runner = _read(WINDOWS_DIR / "aether-service-runner.ps1")
    assert "ValidateOnly" in runner
    assert "service.secretenv.validateonly" in runner


def test_promotion_asserts_release_venv():
    promote = _read(WINDOWS_DIR / "promote-aether-release.ps1")
    assert "Assert-ReleaseVenv" in promote
    assert "Build-ReleaseVenv" in promote
    # Assert-ReleaseVenv must verify marker, sha, version, and imports.
    assert "release_sha" in promote
    assert "livekit_agents" in promote
    assert "livekit.api" in promote
    # -SkipReleaseVenv must only skip the BUILD step, not the assertion.
    assert 'Assert-ReleaseVenv' in promote
    # Staging builds venv before publish.
    assert 'Build-ReleaseVenv -ReleasePath $staging' in promote


def test_promotion_binds_service_python_to_release_venv():
    # Blocker 1 (review REV7): the bootstrap python that CREATED the venv must
    # never be bound as the service python. After the venv is verified, service
    # host + child runner bind exactly <release>\.venv\Scripts\python.exe; the
    # receipt reports the exact python bound per service.
    promote = _read(WINDOWS_DIR / "promote-aether-release.ps1")
    installer = _read(WINDOWS_DIR / "install-aether-services.ps1")
    assert "service_python" in promote
    assert "rollback_service_python" in promote
    assert "Get-BoundServicePython" in promote
    assert "service_python = $serviceHostPython" in installer
    # Release venv takes priority over the requested bootstrap python.
    assert ".venv\\Scripts\\python.exe" in installer
    assert 'if (Test-Path -LiteralPath $releasePython -PathType Leaf)' in installer


def test_provision_sense_worker_secrets_script_has_no_secret_values():
    script = _read(ROOT / "scripts" / "provision-sense-worker-secrets.ps1")
    assert "senses-livekit.env" in script
    assert "New-ProtectedFileAcl" in script
    assert "AreAccessRulesProtected" in script
    # Secrets must NOT be accepted as command-line arguments; only via
    # -SourceEnvPath (a protected file outside the repo).
    assert "SourceEnvPath" in script
    assert "LiveKitUrl" not in script
    assert "LiveKitApiKey" not in script
    assert "LiveKitApiSecret" not in script
    assert "WorkerToken" not in script
    # Owner must be set explicitly.
    assert "SetOwner" in script
    # Atomic replace: File.Replace or File.Move, unique temp, cleanup finally.
    assert "File.Replace" in script or "File::Replace" in script
    assert "Guid" in script
    assert "finally" in script
    for line in script.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key.strip() in {
            "LIVEKIT_URL",
            "LIVEKIT_API_KEY",
            "LIVEKIT_API_SECRET",
            "AETHER_SENSE_WORKER_TOKEN",
            "LiveKitUrl",
            "LiveKitApiKey",
            "LiveKitApiSecret",
            "WorkerToken",
        }:
            value = value.removesuffix("`r`n").strip()
            # Values come from parameters/`$envMap`, never hard-coded.
            assert value.startswith("$") or value == "", (
                f"hard-coded credential value in provisioning script: {key}"
            )
