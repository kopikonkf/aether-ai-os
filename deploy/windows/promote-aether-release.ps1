[CmdletBinding()]
param(
    [string]$RepoPath = "C:\aether\aether-ai-os",
    [string]$AetherHome = "C:\ProgramData\Aether",
    [string]$ReleasesRoot = "C:\aether\releases",
    [string]$RollbackRelease = "81582f70c0ccd3d7b32d364b2be6784cff5ffc31",
    [string]$PythonPath = "",
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8000,
    [int]$HealthTimeoutSeconds = 8,
    [int]$HealthAttempts = 6,
    [switch]$Start
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run this promotion from an elevated PowerShell session."
    }
}

Assert-Administrator

if (-not (Test-Path -LiteralPath $RepoPath -PathType Container)) {
    throw "Repo path not found: $RepoPath"
}
if (-not (Test-Path -LiteralPath $AetherHome -PathType Container)) {
    throw "AETHER_HOME not found: $AetherHome"
}

# 1. Resolve the exact main SHA from the repo (source authority).
$headSha = (git -C $RepoPath rev-parse origin/main 2>$null | Out-String).Trim()
git -C $RepoPath fetch origin main 2>&1 | Out-Null
$headSha = (git -C $RepoPath rev-parse origin/main 2>$null | Out-String).Trim()
if (-not $headSha -or $headSha -notmatch '^[0-9a-f]{40}$') {
    throw "Unable to resolve a clean origin/main SHA"
}
$headDirty = @(git -C $RepoPath status --porcelain 2>$null)
if ($headDirty.Count -gt 0) {
    throw "Repository working tree is not clean before promotion."
}

$targetRelease = Join-Path $ReleasesRoot $headSha
$rollbackPath = Join-Path $ReleasesRoot $RollbackRelease

$receipt = [ordered]@{
    schema = "aether.release-promotion.v1"
    event = "aether.release.promoted"
    promoted_at = (Get-Date).ToUniversalTime().ToString("o")
    target_sha = $headSha
    release_path = $targetRelease
    aether_home = $AetherHome
    rollback_release = $RollbackRelease
    rollback_path = $rollbackPath
    auto_rollback_attempted = $false
    reconciled = @()
    rollback_triggered = $false
}

try {
    # 2. Stage a fresh immutable release dir from the exact commit (no copy of
    #    runtime state, no AETHER_HOME migration).
    if (Test-Path -LiteralPath $targetRelease -PathType Container) {
        throw "Target release already exists (immutable): $targetRelease"
    }
    New-Item -ItemType Directory -Force -Path $targetRelease | Out-Null
    git -C $RepoPath archive $headSha | tar -x -C $targetRelease
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to stage release archive from $headSha"
    }
    $stagedHead = (git -C $targetRelease rev-parse HEAD 2>$null | Out-String).Trim()
    if ($stagedHead -ne $headSha) {
        throw "Staged release HEAD mismatch (promotion aborted before reconcile)"
    }

    # 3. Reconcile Gateway + Watchdog service binary paths to the new release.
    $installer = Join-Path $targetRelease "deploy\windows\install-aether-services.ps1"
    $installerArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $installer,
        "-ReleasePath", $targetRelease,
        "-AetherHome", $AetherHome,
        "-HostAddress", $HostAddress,
        "-Port", [string]$Port
    )
    if ($PythonPath) {
        $installerArgs += @("-PythonPath", $PythonPath)
    }
    & powershell.exe @installerArgs | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "install-aether-services reconcile failed (exit $LASTEXITCODE)"
    }
    $receipt.reconciled = @("AetherGateway", "AetherWatchdog")

    # 4. Health gate after reconcile.
    if ($Start) {
        $healthy = $false
        for ($i = 0; $i -lt $HealthAttempts; $i++) {
            Start-Sleep -Seconds 2
            try {
                $resp = Invoke-WebRequest -Uri "http://$HostAddress`:$Port/health" -TimeoutSec $HealthTimeoutSeconds -UseBasicParsing
                if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 300) {
                    $healthy = $true
                    break
                }
            }
            catch {
            }
        }
if (-not $healthy) {
            $receipt.rollback_triggered = $true
            $receipt.auto_rollback_attempted = $true
            # Reconcile back to the rollback release path (services only).
            $rollbackInstaller = Join-Path $rollbackPath "deploy\windows\install-aether-services.ps1"
            if (Test-Path -LiteralPath $rollbackInstaller -PathType Leaf) {
                & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $rollbackInstaller -ReleasePath $rollbackPath -AetherHome $AetherHome -HostAddress $HostAddress -Port $Port | Out-Null
            }
            throw "Gateway health check failed after promotion; rolled back to $rollbackPath"
        }
    }
}
catch {
    $receipt.failure_phase = "reconcile_or_health"
    $receipt.error = $_.Exception.Message
    $receipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $AetherHome "services\release-promotion-failure.json") -Encoding UTF8
    throw
}

$receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $AetherHome "services\release-promotion.json") -Encoding UTF8
$receipt | ConvertTo-Json -Depth 8
