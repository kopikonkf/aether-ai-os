[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("gateway", "sense-worker")]
    [string]$Role,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$ReleasePath,

    [string]$ServiceName = "",
    [string]$PythonPath = "",
    [string]$AetherHome = "C:\ProgramData\Aether",
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8000,
    [int]$RestartDelaySeconds = 5
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-AetherServiceEvent {
    param([hashtable]$Event)

    $Event["observed_at"] = (Get-Date).ToUniversalTime().ToString("o")
    $line = $Event | ConvertTo-Json -Depth 8 -Compress
    Add-Content -LiteralPath $script:ServiceEventsPath -Value $line -Encoding UTF8
}

function Resolve-AetherPython {
    if ($PythonPath -and (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
        return (Resolve-Path -LiteralPath $PythonPath).Path
    }

    $venvPython = Join-Path $ReleasePath ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        return $venvPython
    }

    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -ne $python) {
        return $python.Source
    }

    $pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($null -ne $pyLauncher) {
        return $pyLauncher.Source
    }

    throw "No Python executable found. Provide -PythonPath or install Python 3.11."
}

function Set-AetherProcessEnvironment {
    $sourcePaths = @(
        (Join-Path $ReleasePath "aether-core\src"),
        (Join-Path $ReleasePath "aether-tools\src"),
        (Join-Path $ReleasePath "aether-gateway\src")
    ) | Where-Object { Test-Path -LiteralPath $_ -PathType Container }

    if ($sourcePaths.Count -gt 0) {
        $existing = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
        $items = @($sourcePaths)
        if ($existing) {
            $items += $existing
        }
        [Environment]::SetEnvironmentVariable("PYTHONPATH", ($items -join [IO.Path]::PathSeparator), "Process")
    }

    $env:AETHER_HOME = $AetherHome
    $env:HOST = $HostAddress
    $env:PORT = [string]$Port
    $env:AETHER_GATEWAY_URL = "http://$($HostAddress):$Port"
    $env:AETHER_SERVICE_NAME = $ServiceName
}

$ReleasePath = (Resolve-Path -LiteralPath $ReleasePath).Path
if (-not $ServiceName) {
    $ServiceName = if ($Role -eq "gateway") { "AetherGateway" } else { "AetherSenseWorker" }
}

$servicesDir = Join-Path $AetherHome "services"
$logsDir = Join-Path $AetherHome "logs"
New-Item -ItemType Directory -Force -Path $servicesDir, $logsDir | Out-Null
$script:ServiceEventsPath = Join-Path $servicesDir "service-events.jsonl"

Set-AetherProcessEnvironment
$python = Resolve-AetherPython
$arguments = switch ($Role) {
    "gateway" { @("-m", "aether_gateway.api.server") }
    "sense-worker" { @("-m", "aether_gateway.browser_senses.worker", "start") }
}

$stdout = Join-Path $logsDir "$ServiceName.out.log"
$stderr = Join-Path $logsDir "$ServiceName.err.log"
$script:AetherChildProcess = $null

Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action {
    if ($script:AetherChildProcess -and -not $script:AetherChildProcess.HasExited) {
        Stop-Process -Id $script:AetherChildProcess.Id -Force -ErrorAction SilentlyContinue
    }
} | Out-Null

Write-AetherServiceEvent @{
    event = "service.runner.ready"
    service = $ServiceName
    role = $Role
    release_path = $ReleasePath
    aether_home = $AetherHome
    python = $python
}

while ($true) {
    $startedAt = (Get-Date).ToUniversalTime()
    Write-AetherServiceEvent @{
        event = "service.child.start"
        service = $ServiceName
        role = $Role
        started_at = $startedAt.ToString("o")
    }

    $script:AetherChildProcess = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $ReleasePath -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden

    $script:AetherChildProcess.WaitForExit()
    $exitCode = $script:AetherChildProcess.ExitCode
    $finishedAt = (Get-Date).ToUniversalTime()

    Write-AetherServiceEvent @{
        event = "service.child.exit"
        service = $ServiceName
        role = $Role
        exit_code = $exitCode
        pid = $script:AetherChildProcess.Id
        uptime_seconds = [math]::Round(($finishedAt - $startedAt).TotalSeconds, 3)
    }

    Start-Sleep -Seconds $RestartDelaySeconds
}