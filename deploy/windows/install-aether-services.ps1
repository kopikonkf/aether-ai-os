[CmdletBinding()]
param(
    [string]$ReleasePath = "",
    [string]$PythonPath = "",
    [string]$AetherHome = "C:\ProgramData\Aether",
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8000,
    [switch]$InstallSenseWorker,
    [switch]$Start
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run this installer from an elevated PowerShell session."
    }
}

function Quote-Arg {
    param([Parameter(Mandatory = $true)][string]$Value)
    return '"' + $Value + '"'
}

function Join-ServiceCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $items = @((Quote-Arg $Executable))
    foreach ($argument in $Arguments) {
        $items += (Quote-Arg $argument)
    }
    return ($items -join ' ')
}

function Install-OrUpdate-Service {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$DisplayName,
        [Parameter(Mandatory = $true)][string]$Description,
        [Parameter(Mandatory = $true)][string]$BinaryPathName,
        [string[]]$DependsOn = @()
    )

    $existing = Get-Service -Name $Name -ErrorAction SilentlyContinue
    if ($null -eq $existing) {
        if ($DependsOn.Count -gt 0) {
            New-Service -Name $Name -DisplayName $DisplayName -Description $Description -BinaryPathName $BinaryPathName -StartupType Automatic -DependsOn $DependsOn | Out-Null
        }
        else {
            New-Service -Name $Name -DisplayName $DisplayName -Description $Description -BinaryPathName $BinaryPathName -StartupType Automatic | Out-Null
        }
    }
    else {
        sc.exe config $Name binPath= "$BinaryPathName" start= auto | Out-Null
        Set-Service -Name $Name -StartupType Automatic
    }

    sc.exe failure $Name reset= 86400 actions= restart/5000/restart/5000/restart/30000 | Out-Null
}

Assert-Administrator

if (-not $ReleasePath) {
    $ReleasePath = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
}
else {
    $ReleasePath = (Resolve-Path -LiteralPath $ReleasePath).Path
}

$runner = Join-Path $ReleasePath "deploy\windows\aether-service-runner.ps1"
$watchdog = Join-Path $ReleasePath "deploy\windows\aether-watchdog.ps1"
if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) {
    throw "Missing service runner: $runner"
}
if (-not (Test-Path -LiteralPath $watchdog -PathType Leaf)) {
    throw "Missing watchdog: $watchdog"
}

$powerShellExe = (Get-Command powershell.exe -ErrorAction Stop).Source
$servicesDir = Join-Path $AetherHome "services"
$logsDir = Join-Path $AetherHome "logs"
New-Item -ItemType Directory -Force -Path $AetherHome, $servicesDir, $logsDir | Out-Null

icacls $AetherHome /inheritance:e /grant "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F" | Out-Null

$commonRunnerArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $runner,
    "-ReleasePath", $ReleasePath,
    "-AetherHome", $AetherHome,
    "-HostAddress", $HostAddress,
    "-Port", [string]$Port
)
if ($PythonPath) {
    $commonRunnerArgs += @("-PythonPath", $PythonPath)
}

$gatewayArgs = $commonRunnerArgs + @("-Role", "gateway", "-ServiceName", "AetherGateway")
$gatewayBin = Join-ServiceCommand $powerShellExe $gatewayArgs
Install-OrUpdate-Service
    -Name "AetherGateway"
    -DisplayName "Aether Gateway"
    -Description "Aether Gateway API service. Runtime state is owned by AETHER_HOME."
    -BinaryPathName $gatewayBin

$installed = @("AetherGateway")

if ($InstallSenseWorker) {
    $senseArgs = $commonRunnerArgs + @("-Role", "sense-worker", "-ServiceName", "AetherSenseWorker")
    $senseBin = Join-ServiceCommand $powerShellExe $senseArgs
    Install-OrUpdate-Service
        -Name "AetherSenseWorker"
        -DisplayName "Aether Sense Worker"
        -Description "Optional Aether LiveKit Sense Worker service."
        -BinaryPathName $senseBin
        -DependsOn @("AetherGateway")
    $installed += "AetherSenseWorker"
}

$watchdogArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $watchdog,
    "-AetherHome", $AetherHome,
    "-HealthUrl", "http://$($HostAddress):$Port/health",
    "-ServiceNames"
) + $installed
$watchdogBin = Join-ServiceCommand $powerShellExe $watchdogArgs
Install-OrUpdate-Service
    -Name "AetherWatchdog"
    -DisplayName "Aether Watchdog"
    -Description "Aether heartbeat and bounded service restart watchdog."
    -BinaryPathName $watchdogBin
    -DependsOn @("AetherGateway")

$manifest = [ordered]@{
    installed_at = (Get-Date).ToUniversalTime().ToString("o")
    release_path = $ReleasePath
    aether_home = $AetherHome
    host = $HostAddress
    port = $Port
    services = $installed + @("AetherWatchdog")
    heartbeat_path = (Join-Path $servicesDir "heartbeats.jsonl")
}
$manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $servicesDir "service-manifest.json") -Encoding UTF8

if ($Start) {
    Start-Service -Name "AetherGateway"
    if ($InstallSenseWorker) {
        Start-Service -Name "AetherSenseWorker"
    }
    Start-Service -Name "AetherWatchdog"
}

$manifest | ConvertTo-Json -Depth 6