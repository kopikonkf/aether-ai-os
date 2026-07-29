[CmdletBinding()]
param(
    [ValidateSet('Start','Status','Stop')]
    [string]$Action = 'Start',
    [string]$AionUiExe = '',
    [int]$Port = 25808
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RuntimeDir = Join-Path $PSScriptRoot '.aether-windows\aionui'
$PidFile = Join-Path $RuntimeDir 'aionui.pid'
$EvidenceFile = Join-Path $RuntimeDir 'aionui-lite-evidence.json'
$StdoutLog = Join-Path $RuntimeDir 'aionui.stdout.log'
$StderrLog = Join-Path $RuntimeDir 'aionui.stderr.log'
New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null

function Write-Step([string]$Message) {
    Write-Host "[AionUi Hybrid Lite] $Message" -ForegroundColor Magenta
}

function Test-Executable([string]$Path) {
    return -not [string]::IsNullOrWhiteSpace($Path) -and (Test-Path -LiteralPath $Path -PathType Leaf)
}

function Resolve-AionUiExecutable {
    if (Test-Executable $AionUiExe) {
        return (Resolve-Path -LiteralPath $AionUiExe).Path
    }

    $command = Get-Command 'AionUi.exe' -ErrorAction SilentlyContinue
    if ($command -and (Test-Executable $command.Source)) {
        return $command.Source
    }

    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\AionUi\AionUi.exe'),
        (Join-Path $env:LOCALAPPDATA 'AionUi\AionUi.exe'),
        (Join-Path $env:ProgramFiles 'AionUi\AionUi.exe')
    )
    if (${env:ProgramFiles(x86)}) {
        $candidates += (Join-Path ${env:ProgramFiles(x86)} 'AionUi\AionUi.exe')
    }

    foreach ($candidate in $candidates) {
        if (Test-Executable $candidate) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    $registryRoots = @(
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
    )
    foreach ($root in $registryRoots) {
        foreach ($entry in @(Get-ItemProperty -Path $root -ErrorAction SilentlyContinue)) {
            if ($entry.DisplayName -notlike '*AionUi*') { continue }
            if ($entry.InstallLocation) {
                $candidate = Join-Path ([string]$entry.InstallLocation) 'AionUi.exe'
                if (Test-Executable $candidate) { return (Resolve-Path -LiteralPath $candidate).Path }
            }
            if ($entry.DisplayIcon) {
                $candidate = ([string]$entry.DisplayIcon).Trim('"').Split(',')[0]
                if (Test-Executable $candidate) { return (Resolve-Path -LiteralPath $candidate).Path }
            }
        }
    }

    throw @'
AionUi.exe was not found.
Install the official Windows x64 AionUi release first, then retry.
You may also pass an explicit path:
  .\START_AIONUI_WINDOWS_LITE.ps1 -Action Start -AionUiExe "C:\path\to\AionUi.exe"
'@
}

function Get-TrackedProcess {
    if (-not (Test-Path -LiteralPath $PidFile)) { return $null }
    $raw = (Get-Content -LiteralPath $PidFile -Raw).Trim()
    $pidValue = 0
    if (-not [int]::TryParse($raw, [ref]$pidValue)) { return $null }
    try { return Get-Process -Id $pidValue -ErrorAction Stop } catch { return $null }
}

function Test-WebUi {
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port" -UseBasicParsing -TimeoutSec 3
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500)
    } catch {
        return $false
    }
}

function Start-AionUiLite {
    $existing = Get-TrackedProcess
    if ($existing -and (Test-WebUi)) {
        Write-Step "Already running as PID $($existing.Id) on port $Port"
        return
    }

    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
    $exe = Resolve-AionUiExecutable
    Write-Step "Starting $exe --webui --port $Port"
    $process = Start-Process `
        -FilePath $exe `
        -ArgumentList @('--webui','--port',"$Port") `
        -WorkingDirectory (Split-Path -Parent $exe) `
        -RedirectStandardOutput $StdoutLog `
        -RedirectStandardError $StderrLog `
        -PassThru
    Set-Content -LiteralPath $PidFile -Value $process.Id -Encoding ASCII

    $deadline = [DateTimeOffset]::UtcNow.AddSeconds(60)
    do {
        Start-Sleep -Milliseconds 750
        if (Test-WebUi) {
            Write-Step "WebUI healthy at http://127.0.0.1:$Port"
            Write-Step "Initial admin credentials, when generated, are recorded in $StdoutLog"
            return
        }
        if ($process.HasExited) {
            throw "AionUi exited with code $($process.ExitCode). Inspect $StdoutLog and $StderrLog"
        }
    } while ([DateTimeOffset]::UtcNow -lt $deadline)

    throw "AionUi did not become reachable within 60 seconds. Inspect $StdoutLog and $StderrLog"
}

function Stop-AionUiLite {
    $process = Get-TrackedProcess
    if (-not $process) {
        Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
        Write-Step 'No tracked AionUi process is running'
        return
    }
    Write-Step "Stopping PID $($process.Id)"
    Stop-Process -Id $process.Id -ErrorAction SilentlyContinue
    try { Wait-Process -Id $process.Id -Timeout 15 -ErrorAction Stop } catch {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
}

function Show-Status {
    $process = Get-TrackedProcess
    $online = Test-WebUi
    $resolvedExe = $null
    try { $resolvedExe = Resolve-AionUiExecutable } catch {}
    $evidence = [ordered]@{
        generated_at = [DateTimeOffset]::UtcNow.ToString('o')
        mode = 'hybrid-lite'
        aionui_executable = $resolvedExe
        online = $online
        url = "http://127.0.0.1:$Port"
        pid = if ($process) { $process.Id } else { $null }
        stdout_log = $StdoutLog
        stderr_log = $StderrLog
        integration_state = 'independent prebuilt AionUi; Aether source route pack is not embedded'
        aether_expected_url = 'http://127.0.0.1:8000/senses'
    }
    $json = $evidence | ConvertTo-Json -Depth 8
    [System.IO.File]::WriteAllText($EvidenceFile, $json + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
    $json
}

switch ($Action) {
    'Start'  { Start-AionUiLite; Show-Status }
    'Status' { Show-Status }
    'Stop'   { Stop-AionUiLite; Show-Status }
}
