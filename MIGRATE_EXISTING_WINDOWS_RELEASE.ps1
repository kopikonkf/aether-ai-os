[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [string]$OldReleaseRoot,
    [string]$NewReleaseRoot = $PSScriptRoot,
    [switch]$OverwriteEnvironment
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Old = (Resolve-Path -LiteralPath $OldReleaseRoot).Path
$New = (Resolve-Path -LiteralPath $NewReleaseRoot).Path
if ($Old -eq $New) { throw 'OldReleaseRoot and NewReleaseRoot must be different folders.' }

$oldPidFile = Join-Path $Old '.aether-windows\gateway.pid'
if (Test-Path -LiteralPath $oldPidFile) {
    try {
        $rawPid = (Get-Content -LiteralPath $oldPidFile -Raw).Trim()
        $oldPid = 0
        if ([int]::TryParse($rawPid, [ref]$oldPid)) {
            $oldProcess = Get-Process -Id $oldPid -ErrorAction SilentlyContinue
            if ($oldProcess) {
                Write-Host "Stopping old Gateway PID $oldPid" -ForegroundColor Cyan
                Stop-Process -Id $oldPid -ErrorAction Stop
                try { Wait-Process -Id $oldPid -Timeout 10 -ErrorAction Stop } catch {
                    Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue
                }
            }
        }
        Remove-Item -LiteralPath $oldPidFile -Force -ErrorAction SilentlyContinue
    } catch {
        Write-Warning "Could not stop the old Gateway automatically: $($_.Exception.Message)"
    }
}

$oldEnv = Join-Path $Old 'aether-core\.env'
$newEnv = Join-Path $New 'aether-core\.env'
if (-not (Test-Path -LiteralPath $oldEnv)) {
    Write-Warning "No existing environment found at $oldEnv"
} elseif ((Test-Path -LiteralPath $newEnv) -and -not $OverwriteEnvironment) {
    throw "Destination environment already exists: $newEnv. Rerun with -OverwriteEnvironment only after reviewing both files."
} else {
    if (Test-Path -LiteralPath $newEnv) {
        Copy-Item -LiteralPath $newEnv -Destination "$newEnv.before-migration.bak" -Force
    }
    Copy-Item -LiteralPath $oldEnv -Destination $newEnv -Force
    Write-Host "Copied environment configuration to $newEnv" -ForegroundColor Green
}

Write-Host ''
Write-Host 'Mutable Aether state was not copied because it lives under AETHER_HOME.' -ForegroundColor Cyan
Write-Host 'Do not copy .venv, .aether-windows, SQLite files, logs, or browser tokens into the new release.' -ForegroundColor Cyan
Write-Host "Next: cd '$New'; .\START_AETHER_WINDOWS_ALPHA.ps1 -Action All" -ForegroundColor Green
