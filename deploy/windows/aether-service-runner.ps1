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
    [int]$RestartDelaySeconds = 5,
    [string]$SecretEnvPath = "",
    [switch]$ValidateOnly
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

# --- Secret env injection (role-scoped allowlist) ---
# Canonical secret file: AETHER_HOME\secrets\senses-livekit.env. Both the Gateway
# and the Sense Worker read it, but each role only receives the keys it needs.
$ALLOWED_SECRET_KEYS = switch ($Role) {
    "gateway" { @("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "LIVEKIT_AGENT_NAME", "AETHER_SENSE_WORKER_TOKEN") }
    "sense-worker" { @("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "LIVEKIT_AGENT_NAME", "AETHER_SENSE_WORKER_TOKEN") }
    default { @() }
}
$REQUIRED_SECRET_KEYS = switch ($Role) {
    "gateway" { @("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET") }
    "sense-worker" { @("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "AETHER_SENSE_WORKER_TOKEN") }
    default { @() }
}

if ($SecretEnvPath) {
    if ($Role -notin @("gateway", "sense-worker")) {
        $msg = "SecretEnvPath is only valid for roles gateway or sense-worker."
        Write-AetherServiceEvent @{ event = "service.secretenv.blocked"; service = $ServiceName; reason = $msg }
        throw $msg
    }
    if (-not (Test-Path -LiteralPath $SecretEnvPath -PathType Leaf)) {
        $msg = "SecretEnvPath $SecretEnvPath not found. Service cannot start without credentials."
        Write-AetherServiceEvent @{ event = "service.secretenv.blocked"; service = $ServiceName; reason = $msg }
        throw $msg
    }
    # Reject reparse point (symlink, junction, mount point).
    $fileInfo = Get-Item -LiteralPath $SecretEnvPath -Force -ErrorAction Stop
    if ($fileInfo.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        $msg = "SecretEnvPath $SecretEnvPath is a reparse point. Refusing to load."
        Write-AetherServiceEvent @{ event = "service.secretenv.blocked"; service = $ServiceName; reason = $msg }
        throw $msg
    }
    # Exact DACL verifier: SYSTEM + Administrators only, no inheritance, no
    # unexpected Allow/Deny ACE, every allowed SID must have FullControl.
    $acl = Get-Acl -LiteralPath $SecretEnvPath -ErrorAction Stop
    if (-not $acl.AreAccessRulesProtected) {
        $msg = "SecretEnvPath $SecretEnvPath has unprotected DACL (inheritance enabled). Refusing to load."
        Write-AetherServiceEvent @{ event = "service.secretenv.blocked"; service = $ServiceName; reason = $msg }
        throw $msg
    }
    $expectedSids = @{ "S-1-5-18" = $false; "S-1-5-32-544" = $false }
    $fullControl = [System.Security.AccessControl.FileSystemRights]::FullControl
    foreach ($rule in $acl.Access) {
        if ($rule.AccessControlType -eq "Deny") {
            $msg = "SecretEnvPath $SecretEnvPath has a Deny ACE (unexpected). Refusing to load."
            Write-AetherServiceEvent @{ event = "service.secretenv.blocked"; service = $ServiceName; reason = $msg }
            throw $msg
        }
        $sid = $rule.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
        if ($sid -eq "S-1-5-18" -or $sid -eq "S-1-5-32-544") {
            # Every allowed SID must be granted FullControl and nothing less.
            if (($rule.FileSystemRights -band $fullControl) -ne $fullControl) {
                $msg = "SecretEnvPath $SecretEnvPath grants $sid rights other than FullControl. Refusing to load."
                Write-AetherServiceEvent @{ event = "service.secretenv.blocked"; service = $ServiceName; reason = $msg }
                throw $msg
            }
            # The ACE itself must not carry inheritance flags (it is on a file).
            if ($rule.InheritanceFlags -ne [System.Security.AccessControl.InheritanceFlags]::None) {
                $msg = "SecretEnvPath $SecretEnvPath has an inherited-flag ACE for $sid. Refusing to load."
                Write-AetherServiceEvent @{ event = "service.secretenv.blocked"; service = $ServiceName; reason = $msg }
                throw $msg
            }
            $expectedSids[$sid] = $true
        }
        else {
            $msg = "SecretEnvPath $SecretEnvPath has unexpected ACE for $sid. Refusing to load."
            Write-AetherServiceEvent @{ event = "service.secretenv.blocked"; service = $ServiceName; reason = $msg }
            throw $msg
        }
    }
    foreach ($sid in $expectedSids.Keys) {
        if (-not $expectedSids[$sid]) {
            $msg = "SecretEnvPath $SecretEnvPath is missing required SID $sid."
            Write-AetherServiceEvent @{ event = "service.secretenv.blocked"; service = $ServiceName; reason = $msg }
            throw $msg
        }
    }
    if ($acl.Owner -notmatch "(S-1-5-18|S-1-5-32-544|NT AUTHORITY\\SYSTEM|BUILTIN\\Administrators)") {
        $msg = "SecretEnvPath $SecretEnvPath owner is not SYSTEM or Administrators. Refusing to load."
        Write-AetherServiceEvent @{ event = "service.secretenv.blocked"; service = $ServiceName; reason = $msg }
        throw $msg
    }
    # Strict parser: reject unknown/duplicate/malformed/empty keys.
    $keysSeen = @{}
    $lines = Get-Content -LiteralPath $SecretEnvPath -Encoding UTF8 -ErrorAction Stop
    foreach ($raw in $lines) {
        $line = $raw.Trim()
        if (-not $line) {
            $msg = "SecretEnvPath $SecretEnvPath contains empty line. Refusing to load."
            Write-AetherServiceEvent @{ event = "service.secretenv.blocked"; service = $ServiceName; reason = $msg }
            throw $msg
        }
        if ($line.StartsWith("#")) { continue }
        $eq = $line.IndexOf("=")
        if ($eq -le 0) {
            $msg = "SecretEnvPath $SecretEnvPath contains a malformed line (no '='). Refusing to load."
            Write-AetherServiceEvent @{ event = "service.secretenv.blocked"; service = $ServiceName; reason = $msg }
            throw $msg
        }
        $key = $line.Substring(0, $eq).Trim()
        $value = $line.Substring($eq + 1).Trim()
        if ($key -notin $ALLOWED_SECRET_KEYS) {
            $msg = "SecretEnvPath $SecretEnvPath contains unknown key: $key. Refusing to load."
            Write-AetherServiceEvent @{ event = "service.secretenv.blocked"; service = $ServiceName; reason = $msg }
            throw $msg
        }
        if ($keysSeen.ContainsKey($key)) {
            $msg = "SecretEnvPath $SecretEnvPath contains duplicate key: $key. Refusing to load."
            Write-AetherServiceEvent @{ event = "service.secretenv.blocked"; service = $ServiceName; reason = $msg }
            throw $msg
        }
        $keysSeen[$key] = $true
        if (-not $value) {
            $msg = "SecretEnvPath $SecretEnvPath has empty value for $key. Refusing to load."
            Write-AetherServiceEvent @{ event = "service.secretenv.blocked"; service = $ServiceName; reason = $msg }
            throw $msg
        }
        if ($value -match "[\r\n]") {
            $msg = "SecretEnvPath $SecretEnvPath contains malformed value for $key (newline). Refusing to load."
            Write-AetherServiceEvent @{ event = "service.secretenv.blocked"; service = $ServiceName; reason = $msg }
            throw $msg
        }
        [Environment]::SetEnvironmentVariable($key, $value, "Process")
    }
    # Verify all required keys are present and non-empty.
    foreach ($rk in $REQUIRED_SECRET_KEYS) {
        if (-not $keysSeen.ContainsKey($rk)) {
            $msg = "SecretEnvPath $SecretEnvPath is missing required key: $rk."
            Write-AetherServiceEvent @{ event = "service.secretenv.blocked"; service = $ServiceName; reason = $msg }
            throw $msg
        }
    }
    Write-AetherServiceEvent @{ event = "service.secretenv.loaded"; service = $ServiceName; secret_env_path = $SecretEnvPath }
}

# --- ValidateOnly: exercise the exact secret boundary without starting the
# child process. Used by the installer as the pre-SCM-mutation preflight (the
# promotion gates LiveKit wiring behind -InstallSenseWorker, so an installer
# running without that flag never reads this file). Failures above already
# threw; a successful validation exits cleanly.
if ($ValidateOnly) {
    Write-AetherServiceEvent @{ event = "service.secretenv.validateonly"; service = $ServiceName; ok = $true }
    exit 0
}

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