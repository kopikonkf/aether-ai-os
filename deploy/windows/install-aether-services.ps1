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

    if ($RequestedPath) {
        if (-not (Test-Path -LiteralPath $RequestedPath -PathType Leaf)) {
            throw "Python executable not found: $RequestedPath"
        }
        return (Resolve-Path -LiteralPath $RequestedPath).Path
    }

    $releasePython = Join-Path $ResolvedReleasePath ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $releasePython -PathType Leaf) {
        return (Resolve-Path -LiteralPath $releasePython).Path
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

$gatewayArgs = $commonRunnerArgs + @("-Role", "gateway", "-ServiceName", "AetherGateway")
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
    $senseArgs = $commonRunnerArgs + @("-Role", "sense-worker", "-ServiceName", "AetherSenseWorker")
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
    aether_home = $AetherHome
    host = $HostAddress
    port = $Port
    service_host = $serviceHost
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
