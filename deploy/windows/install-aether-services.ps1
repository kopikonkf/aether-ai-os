[CmdletBinding()]
param(
    [string]$ReleasePath = "",
    [string]$PythonPath = "",
    [string]$ServicePythonPath = "",
    [string]$AetherHome = "C:\ProgramData\Aether",
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8000,
    [string]$TargetSha = "",
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

function Invoke-ServiceControl {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    & sc.exe @Arguments | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "sc.exe failed with exit code ${LASTEXITCODE}: $($Arguments -join ' ')"
    }
}

function Resolve-ServiceHostPython {
    param(
        [string]$RequestedPath,
        [Parameter(Mandatory = $true)][string]$ResolvedReleasePath
    )

    # The verified release venv is the authoritative runtime Python for the
    # immutable release. A promotion that built/verified <release>\.venv MUST
    # bind the service host + child runner to exactly that venv (bootstrap
    # python is only for CREATING the venv, never for running services).
    $releasePython = Join-Path $ResolvedReleasePath ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $releasePython -PathType Leaf) {
        return (Resolve-Path -LiteralPath $releasePython).Path
    }

    # No release venv: fall back to the requested bootstrap/legacy python, then
    # to a system python. This keeps rollback to a pre-venv release working and
    # still fails closed rather than silently binding something unexpected.
    if ($RequestedPath) {
        if (-not (Test-Path -LiteralPath $RequestedPath -PathType Leaf)) {
            throw "Python executable not found: $RequestedPath"
        }
        return (Resolve-Path -LiteralPath $RequestedPath).Path
    }

    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -ne $python) {
        return $python.Source
    }

    throw "No python.exe found. Provide -PythonPath or create the release virtual environment."
}

function New-ServiceHostCommand {
    param(
        [Parameter(Mandatory = $true)][string]$ServiceName,
        [Parameter(Mandatory = $true)][string]$HostPython,
        [Parameter(Mandatory = $true)][string]$HostScript,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$EventLogPath,
        [Parameter(Mandatory = $true)][string]$ChildExecutable,
        [Parameter(Mandatory = $true)][string[]]$ChildArguments
    )

    $hostArgs = @(
        $HostScript,
        "--service-name", $ServiceName,
        "--working-directory", $WorkingDirectory,
        "--event-log-path", $EventLogPath,
        "--",
        $ChildExecutable
    ) + $ChildArguments

    return Join-ServiceCommand -Executable $HostPython -Arguments $hostArgs
}

function Install-OrUpdate-Service {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$DisplayName,
        [Parameter(Mandatory = $true)][string]$Description,
        [Parameter(Mandatory = $true)][string]$BinaryPathName,
        [string[]]$DependsOn = @()
    )

    # Test seam: skip actual SCM operations when the env var is set, so the
    # argv-composition regression test can observe args without mutating services.
    $skipSCM = [Environment]::GetEnvironmentVariable("AETHER_INSTALLER_SKIP_SCM", "Process")
    if ($skipSCM) {
        Write-Output "[seam] skip SCM for $Name"
        return
    }

    $existing = Get-Service -Name $Name -ErrorAction SilentlyContinue
    if ($null -eq $existing) {
        if ($DependsOn.Count -gt 0) {
            New-Service -Name $Name -DisplayName $DisplayName -Description $Description -BinaryPathName $BinaryPathName -StartupType Automatic -DependsOn $DependsOn | Out-Null
        }
        else {
            New-Service -Name $Name -DisplayName $DisplayName -Description $Description -BinaryPathName $BinaryPathName -StartupType Automatic | Out-Null
        }
    }

    $dependencyValue = if ($DependsOn.Count -gt 0) {
        $DependsOn -join "/"
    }
    else {
        "/"
    }
    Invoke-ServiceControl -Arguments @(
        "config", $Name,
        "binPath=", $BinaryPathName,
        "start=", "auto",
        "depend=", $dependencyValue
    )
    Invoke-ServiceControl -Arguments @("description", $Name, $Description)
    Invoke-ServiceControl -Arguments @(
        "failure", $Name,
        "reset=", "86400",
        "actions=", "restart/5000/restart/5000/restart/30000"
    )
    # Treat a clean service-host exit with a service-specific error as a failure,
    # so SCM recovery applies when the supervised child exits unexpectedly.
    Invoke-ServiceControl -Arguments @("failureflag", $Name, "1")
}

function New-ProtectedAcl {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][bool]$IsContainer
    )

    $acl = if ($IsContainer) {
        New-Object System.Security.AccessControl.DirectorySecurity
    }
    else {
        New-Object System.Security.AccessControl.FileSecurity
    }

    $acl.SetAccessRuleProtection($true, $false)

    $inherit = [System.Security.AccessControl.InheritanceFlags]::None
    if ($IsContainer) {
        $inherit = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
            [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
    }

    foreach ($sid in @("S-1-5-18", "S-1-5-32-544")) {
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            (New-Object System.Security.Principal.SecurityIdentifier $sid),
            [System.Security.AccessControl.FileSystemRights]::FullControl,
            $inherit,
            [System.Security.AccessControl.PropagationFlags]::None,
            [System.Security.AccessControl.AccessControlType]::Allow
        )
        $acl.AddAccessRule($rule)
    }

    return $acl
}

function Assert-ProtectedAcl {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][bool]$IsContainer,
        [string]$Label = $Path
    )

    $targetAcl = Get-Acl -LiteralPath $Path
    $requiredRules = @{
        "S-1-5-18" = $false
        "S-1-5-32-544" = $false
    }
    $aclViolations = @()
    if (-not $targetAcl.AreAccessRulesProtected) {
        $aclViolations += "inheritance_not_disabled"
    }
    $hasContainerInherit = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit
    $hasObjectInherit = [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
    foreach ($rule in $targetAcl.Access) {
        try {
            $sid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
        }
        catch {
            $sid = [string]$rule.IdentityReference
        }
        if ($sid -notin @($requiredRules.Keys)) {
            $aclViolations += "unexpected_rule:${sid}:$($rule.AccessControlType)"
            continue
        }
        $ruleIsFullControlAllow = (
            $rule.AccessControlType -eq "Allow" -and
            ($rule.FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::FullControl) -eq [System.Security.AccessControl.FileSystemRights]::FullControl
        )
        $inheritsOk = $true
        if ($IsContainer) {
            $inheritsOk = (
                [bool]($rule.InheritanceFlags -band $hasContainerInherit) -and
                [bool]($rule.InheritanceFlags -band $hasObjectInherit)
            )
        }
        if (-not ($ruleIsFullControlAllow -and $inheritsOk)) {
            $aclViolations += "required_rule_incomplete:${sid}:rights=$($rule.FileSystemRights):inherit=$($rule.InheritanceFlags)"
        }
        else {
            $requiredRules[$sid] = $true
        }
    }
    foreach ($sid in @($requiredRules.Keys)) {
        if (-not $requiredRules[$sid]) {
            $aclViolations += "required_sid_missing:${sid}"
        }
    }
    if ($aclViolations.Count -gt 0) {
        throw "ACL postcondition verification failed for ${Label}: $($aclViolations -join ', ')"
    }
}

function Ensure-ProtectedAetherHome {
    param(
        [Parameter(Mandatory = $true)][string]$Path
    )

    $homeExistedBefore = Test-Path -LiteralPath $Path -PathType Container

    if (-not $homeExistedBefore) {
        New-Item -ItemType Directory -Force -Path $Path | Out-Null
        $protectedAcl = New-ProtectedAcl -Path $Path -IsContainer $true
        Set-Acl -LiteralPath $Path -AclObject $protectedAcl
        Assert-ProtectedAcl -Path $Path -IsContainer $true -Label "AETHER_HOME(new)"
    }
    else {
        # Existing AETHER_HOME must already be protected with exactly SYSTEM +
        # Administrators. Never re-enable inheritance (which would broaden the
        # DACL); assert the pre-existing postcondition instead.
        Assert-ProtectedAcl -Path $Path -IsContainer $true -Label "AETHER_HOME(existing)"
    }

    return $homeExistedBefore
}

function Assert-LiveKitSecretPreflight {
    <#
    Blocker 2 (review REV7): LiveKit wiring is OPTIONAL. When -InstallSenseWorker
    is NOT selected, the Gateway keeps its secret-independent startup path (no
    -SecretEnvPath, no dependency on the canonical secret file). When it IS
    selected, the secret file must be valid BEFORE any SCM mutation, not after
    services are rebound. This preflight invokes the runner's own exact
    validator (-ValidateOnly) so there is exactly ONE credential boundary.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Runner,
        [Parameter(Mandatory = $true)][string]$SecretPath,
        [Parameter(Mandatory = $true)][string]$ReleasePath,
        [Parameter(Mandatory = $true)][string]$AetherHome
    )
    if (-not (Test-Path -LiteralPath $SecretPath -PathType Leaf)) {
        throw "LiveKit secrets not provisioned: $SecretPath. Run provision-sense-worker-secrets.ps1 before installing with -InstallSenseWorker."
    }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Runner `
        -Role gateway `
        -ReleasePath $ReleasePath `
        -AetherHome $AetherHome `
        -SecretEnvPath $SecretPath `
        -ValidateOnly | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "LiveKit secret preflight failed (exit $LASTEXITCODE): $SecretPath"
    }
}

# --- Test seam (AETHER_INSTALLER_SKIP_SCM=1) ---
# Regression tests observe the composed service argv without touching SCM or
# Windows-only ACL/administrator steps. Production never sets this.
$skipSCM = [Environment]::GetEnvironmentVariable("AETHER_INSTALLER_SKIP_SCM", "Process")
if ($skipSCM) {
    if (-not $ReleasePath) {
        $ReleasePath = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
    }
    else {
        $ReleasePath = (Resolve-Path -LiteralPath $ReleasePath).Path
    }
    $runner = Join-Path $ReleasePath "deploy\windows\aether-service-runner.ps1"
    $runnerSupportsSecretEnv = $false
    if (Test-Path -LiteralPath $runner -PathType Leaf) {
        $runnerText = Get-Content -LiteralPath $runner -Raw -ErrorAction SilentlyContinue
        $runnerSupportsSecretEnv = ($null -ne $runnerText -and $runnerText.Contains('$SecretEnvPath'))
    }
    $gatewayArgs = @("-Role", "gateway", "-ServiceName", "AetherGateway")
    $senseArgs = @()
    if ($InstallSenseWorker -and $runnerSupportsSecretEnv) {
        $livekitSecretPath = Join-Path $AetherHome "secrets\senses-livekit.env"
        $gatewayArgs += @("-SecretEnvPath", $livekitSecretPath)
        $senseArgs = @("-Role", "sense-worker", "-ServiceName", "AetherSenseWorker", "-SecretEnvPath", $livekitSecretPath)
        # Optional executable preflight hook (test host): the seam simulates the
        # production pre-SCM gate. Production never sets this env var.
        if ([Environment]::GetEnvironmentVariable("AETHER_INSTALLER_ENFORCE_PREFLIGHT", "Process")) {
            Assert-LiveKitSecretPreflight -Runner $runner -SecretPath $livekitSecretPath -ReleasePath $ReleasePath -AetherHome $AetherHome
        }
    }
    # Blocker 1 (review REV7): the seam reports the python the real installer
    # would bind for the service host, so the regression can assert the release
    # venv wins over any bootstrap -PythonPath.
    $seamHostPython = Resolve-ServiceHostPython -RequestedPath $PythonPath -ResolvedReleasePath $ReleasePath
    $argvLog = [Environment]::GetEnvironmentVariable("AETHER_SERVICE_ARGV_LOG", "Process")
    if ($argvLog) {
        $payload = @{
            runner = $runner
            gateway_args = $gatewayArgs
            sense_args = $senseArgs
            runner_supports_secret_env = $runnerSupportsSecretEnv
            service_python = $seamHostPython
        }
        $payload | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $argvLog -Encoding UTF8
    }
    exit 0
}

Assert-Administrator

$homePreExists = Ensure-ProtectedAetherHome -Path $AetherHome

$servicesDir = Join-Path $AetherHome "services"
$logsDir = Join-Path $AetherHome "logs"
$serviceEventsPath = Join-Path $servicesDir "service-events.jsonl"
New-Item -ItemType Directory -Force -Path $servicesDir, $logsDir | Out-Null

$servicesAcl = New-ProtectedAcl -Path $servicesDir -IsContainer $true
Set-Acl -LiteralPath $servicesDir -AclObject $servicesAcl
$logsAcl = New-ProtectedAcl -Path $logsDir -IsContainer $true
Set-Acl -LiteralPath $logsDir -AclObject $logsAcl

if (-not $ReleasePath) {
    $ReleasePath = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
}
else {
    $ReleasePath = (Resolve-Path -LiteralPath $ReleasePath).Path
}

$runner = Join-Path $ReleasePath "deploy\windows\aether-service-runner.ps1"
$watchdog = Join-Path $ReleasePath "deploy\windows\aether-watchdog.ps1"
$serviceHost = Join-Path $ReleasePath "deploy\windows\aether-windows-service.py"
foreach ($asset in @($runner, $watchdog, $serviceHost)) {
    if (-not (Test-Path -LiteralPath $asset -PathType Leaf)) {
        throw "Missing Windows service asset: $asset"
    }
}

$serviceHostPython = Resolve-ServiceHostPython -RequestedPath $PythonPath -ResolvedReleasePath $ReleasePath
$powerShellExe = (Get-Command powershell.exe -ErrorAction Stop).Source

$commonRunnerArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $runner,
    "-ReleasePath", $ReleasePath,
    "-AetherHome", $AetherHome,
    "-HostAddress", $HostAddress,
    "-Port", [string]$Port,
    "-PythonPath", $serviceHostPython
)

# Capability-aware secret injection (Blocker 2, review REV7): -SecretEnvPath is
# an OPTIONAL LiveKit capability. It is only passed when BOTH the capability is
# explicitly enabled (-InstallSenseWorker) AND the runner in THIS release
# understands it. A plain deploy without -InstallSenseWorker must keep the
# Gateway on its secret-independent startup path (no dependency on the
# canonical senses-livekit.env). Rollback releases (e.g. 956a48a) predate the
# parameter; passing it would fail the child service startup.
$runnerSupportsSecretEnv = $false
if (Test-Path -LiteralPath $runner -PathType Leaf) {
    $runnerText = Get-Content -LiteralPath $runner -Raw -ErrorAction SilentlyContinue
    $runnerSupportsSecretEnv = ($null -ne $runnerText -and $runnerText.Contains('$SecretEnvPath'))
}
$livekitEnabled = ($InstallSenseWorker -and $runnerSupportsSecretEnv)
$livekitSecretPath = Join-Path $AetherHome "secrets\senses-livekit.env"

# With the capability flag the secrets must be valid BEFORE any SCM mutation
# (fail before services are rebound, never after). Without the flag the
# Gateway never reads the file, so no preflight is needed.
if ($livekitEnabled) {
    Assert-LiveKitSecretPreflight -Runner $runner -SecretPath $livekitSecretPath -ReleasePath $ReleasePath -AetherHome $AetherHome
}

$gatewayArgs = @($commonRunnerArgs + @("-Role", "gateway", "-ServiceName", "AetherGateway"))
if ($livekitEnabled) {
    $gatewayArgs += @("-SecretEnvPath", $livekitSecretPath)
}
$gatewayBin = New-ServiceHostCommand `
    -ServiceName "AetherGateway" `
    -HostPython $serviceHostPython `
    -HostScript $serviceHost `
    -WorkingDirectory $ReleasePath `
    -EventLogPath $serviceEventsPath `
    -ChildExecutable $powerShellExe `
    -ChildArguments $gatewayArgs
Install-OrUpdate-Service -Name "AetherGateway" -DisplayName "Aether Gateway" -Description "Aether Gateway API service. Runtime state is owned by AETHER_HOME." -BinaryPathName $gatewayBin

$installed = @("AetherGateway")

if ($InstallSenseWorker) {
    $senseArgs = @($commonRunnerArgs + @("-Role", "sense-worker", "-ServiceName", "AetherSenseWorker"))
    if ($livekitEnabled) {
        $senseArgs += @("-SecretEnvPath", $livekitSecretPath)
    }
    $senseBin = New-ServiceHostCommand `
        -ServiceName "AetherSenseWorker" `
        -HostPython $serviceHostPython `
        -HostScript $serviceHost `
        -WorkingDirectory $ReleasePath `
        -EventLogPath $serviceEventsPath `
        -ChildExecutable $powerShellExe `
        -ChildArguments $senseArgs
    Install-OrUpdate-Service -Name "AetherSenseWorker" -DisplayName "Aether Sense Worker" -Description "Optional Aether LiveKit Sense Worker service." -BinaryPathName $senseBin -DependsOn @("AetherGateway")
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
$watchdogBin = New-ServiceHostCommand `
    -ServiceName "AetherWatchdog" `
    -HostPython $serviceHostPython `
    -HostScript $serviceHost `
    -WorkingDirectory $ReleasePath `
    -EventLogPath $serviceEventsPath `
    -ChildExecutable $powerShellExe `
    -ChildArguments $watchdogArgs
# Watchdog deliberately has no Gateway dependency. It must remain startable
# while Gateway is fully stopped so it can perform bounded recovery.
Install-OrUpdate-Service -Name "AetherWatchdog" -DisplayName "Aether Watchdog" -Description "Aether heartbeat and bounded service restart watchdog." -BinaryPathName $watchdogBin

$manifest = [ordered]@{
    installed_at = (Get-Date).ToUniversalTime().ToString("o")
    release_path = $ReleasePath
    target_sha = $TargetSha
    aether_home = $AetherHome
    host = $HostAddress
    port = $Port
    service_host = $serviceHost
    service_python = $serviceHostPython
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
