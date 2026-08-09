[CmdletBinding()]
param(
    [string]$RepoPath = "C:\aether\aether-ai-os",
    [string]$AetherHome = "C:\ProgramData\Aether",
    [string]$ReleasesRoot = "C:\aether\releases",
    [string]$RollbackRelease = "81582f70c0ccd3d7b32d364b2be6784cff5ffc31",
    [string]$PythonPath = "",
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8000,
    [Parameter(Mandatory = $true)][string]$ExpectedTargetSha,
    [int]$HealthTimeoutSeconds = 8,
    [int]$HealthAttempts = 6,
    [switch]$AllowNonElevated,
    [switch]$SkipAclCheck,
    [switch]$Start,
    [switch]$SkipValidate,
    [switch]$IncludeSenseWorker,
    [switch]$SkipReleaseVenv
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Test observation hooks (env-gated; PRODUCTION never sets these).
#
# AETHER_PROMO_INSTALL_CMD   : path to a .ps1 invoked instead of
#   "powershell.exe install-aether-services.ps1". It receives
#   -ReleasePath <path> -TargetSha <sha> -AetherHome <path>
#   -HostAddress <addr> -Port <port> -Phase <promote|rollback> and its exit
#   code decides success/failure. The real installer writes the live
#   AETHER_HOME\services\service-manifest.json; the seam must do the same for
#   the post-rollback live-manifest verification to be meaningful.
# AETHER_PROMO_RESTART_CMD   : path to a .ps1 invoked instead of the real
#   Get-Service/Restart-Service loop. It receives -ReleasePath <path> and its
#   exit code decides restart success/failure. Restart failures are NEVER
#   swallowed in either path.
# AETHER_PROMO_HEALTH_CMD    : path to a .ps1 printing True/False as the
#   health probe result. Default: real HTTP probe on HostAddress:Port/health.
# AETHER_PROMO_SERVICE_CMD   : path to a .ps1 invoked with -ReleasePath that
#   prints a JSON array of observed services, including the LIVE process:
#   [ { name, running, path, pid, cmdline }, ... ]. Default: real
#   Win32_Service.ProcessId correlated with Win32_Process.CommandLine.
#
# The default (unset) behaviour is always the real production path.
# ---------------------------------------------------------------------------

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run this promotion from an elevated PowerShell session."
    }
}

function Assert-ProtectedAcl {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][bool]$IsContainer,
        [string]$Label = $Path
    )

    $hook = $env:AETHER_PROMO_ACL_CMD
    if ($hook -and (Test-Path -LiteralPath $hook -PathType Leaf)) {
        & $hook -Path $Path -Label $Label
        if ($LASTEXITCODE -ne 0) {
            throw "ACL postcondition verification failed for ${Label} (hook exit $LASTEXITCODE)"
        }
        return
    }

    $targetAcl = Get-Acl -LiteralPath $Path
    $requiredRules = @{ "S-1-5-18" = $false; "S-1-5-32-544" = $false }
    $aclViolations = @()
    if (-not $targetAcl.AreAccessRulesProtected) {
        $aclViolations += "inheritance_not_disabled"
    }
    $hasCI = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit
    $hasOI = [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
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
        $isFullAllow = (
            $rule.AccessControlType -eq "Allow" -and
            ($rule.FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::FullControl) -eq [System.Security.AccessControl.FileSystemRights]::FullControl
        )
        $inheritsOk = $true
        if ($IsContainer) {
            $inheritsOk = (
                [bool]($rule.InheritanceFlags -band $hasCI) -and
                [bool]($rule.InheritanceFlags -band $hasOI)
            )
        }
        if (-not ($isFullAllow -and $inheritsOk)) {
            $aclViolations += "required_rule_incomplete:${sid}"
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

function Confirm-ServiceBoundToRelease {
    param(
        [string[]]$Names,
        [string]$ReleasePath
    )

    $hook = $env:AETHER_PROMO_SERVICE_CMD
    if ($hook -and (Test-Path -LiteralPath $hook -PathType Leaf)) {
        $out = (& $hook -ReleasePath $ReleasePath | Out-String).Trim()
        if ([string]::IsNullOrWhiteSpace($out)) {
            throw "Service observation hook returned nothing for $ReleasePath"
        }
        # Flatten: ConvertFrom-Json on a JSON array string must be enumerated
        # element-by-element (never wrapped), so `$states[0]` is a service
        # object and not the whole array.
        $states = @(($out | ConvertFrom-Json) | ForEach-Object { $_ })
        $bad = @()
        foreach ($name in $Names) {
            $s = @($states | Where-Object { $_.name -eq $name } | Select-Object -First 1)
            if ($s.Count -ne 1) {
                $bad += "$name(not observed)"
                continue
            }
            $running = $false
            try { $running = [bool]$s[0].running } catch { $running = $false }
            $pathOk = ([string]$s[0].path -match [regex]::Escape($ReleasePath))
            $pidOk = $false
            try { $pidOk = ([int]$s[0].pid -gt 0) } catch { $pidOk = $false }
            $cmdlineOk = ([string]$s[0].cmdline -match [regex]::Escape($ReleasePath))
            if (-not $running -or -not $pathOk -or -not $pidOk -or -not $cmdlineOk) {
                $bad += "$name(not running/path/pid/cmdline bound to $ReleasePath)"
            }
        }
        if ($bad.Count -gt 0) {
            throw "Service running-path assertion failed: $($bad -join '; ')"
        }
        return $true
    }

    $bad = @()
    foreach ($name in $Names) {
        $svc = Get-CimInstance Win32_Service -Filter "Name='$name'" -ErrorAction SilentlyContinue
        if ($null -eq $svc) {
            $bad += "$name(service missing)"
            continue
        }
        $svcPid = 0
        try { $svcPid = [int]$svc.ProcessId } catch { $svcPid = 0 }
        if ([string]$svc.PathName -notmatch [regex]::Escape($ReleasePath)) {
            $bad += "$name(payload path does not reference $ReleasePath)"
        }
        if ([string]$svc.State -ne "Running" -or $svcPid -le 0) {
            $bad += "$name(service not Running or no live PID)"
            continue
        }
        # Prove the LIVE process: the SCM PID must exist and its command line
        # must reference the release we just promoted/rolled back to.
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$svcPid" -ErrorAction SilentlyContinue
        if ($null -eq $proc) {
            $bad += "$name(live process missing for PID $svcPid)"
        }
        elseif ([string]$proc.CommandLine -notmatch [regex]::Escape($ReleasePath)) {
            $bad += "$name(live process command line does not reference $ReleasePath)"
        }
    }
    if ($bad.Count -gt 0) {
        throw "Service running-path assertion failed: $($bad -join '; ')"
    }
    return $true
}

function Invoke-Git {
    # Run git without letting Windows PowerShell 5.1 turn git's normal stderr
    # progress (e.g. "From <remote>") into a terminating NativeCommandError.
    param([string[]]$GitArgs)
    $previousEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & git @GitArgs 2>&1 | Out-Null
        return $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousEap
    }
}

function Invoke-GitCapture {
    # Invoke-Git variant that also captures combined output.
    param([string[]]$GitArgs)
    $previousEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = (& git @GitArgs 2>&1 | Out-String).Trim()
        return [pscustomobject]@{ Output = $output; ExitCode = $LASTEXITCODE }
    }
    finally {
        $ErrorActionPreference = $previousEap
    }
}

if (-not $AllowNonElevated) {
    Assert-Administrator
}

if (-not (Test-Path -LiteralPath $RepoPath -PathType Container)) {
    throw "Repo path not found: $RepoPath"
}
if (-not (Test-Path -LiteralPath $AetherHome -PathType Container)) {
    throw "AETHER_HOME not found: $AetherHome"
}
New-Item -ItemType Directory -Force -Path (Join-Path $AetherHome "services") | Out-Null

# A mutating promotion always restarts services and runs the running-path and
# health gates. Refuse to run without -Start BEFORE any SCM mutation.
if (-not $Start) {
    throw "Promotion mutates Windows service configuration and therefore requires -Start (restart + running-path + health gates are mandatory)."
}

# ---- Resolve exact target SHA (source authority) ----------------------------
$fetchExit = Invoke-Git -GitArgs @("-C", $RepoPath, "fetch", "origin", "main")
if ($fetchExit -ne 0) {
    throw "git fetch origin main failed (exit $fetchExit)"
}
$originMainResult = Invoke-GitCapture -GitArgs @("-C", $RepoPath, "rev-parse", "origin/main")
$originMain = $originMainResult.Output.Trim()
if ($originMainResult.ExitCode -ne 0 -or $originMain -notmatch '^[0-9a-f]{40}$') {
    throw "Unable to resolve origin/main SHA"
}
if ($ExpectedTargetSha -ne $originMain) {
    throw "Expected-target-SHA guard failed: requested $ExpectedTargetSha, origin/main = $originMain"
}
$statusResult = Invoke-GitCapture -GitArgs @("-C", $RepoPath, "status", "--porcelain")
$dirty = @()
if ($statusResult.Output) {
    $dirty = @($statusResult.Output -split "`r?`n" | Where-Object { $_.Trim() -ne "" })
}
if ($dirty.Count -gt 0 -and -not $SkipValidate) {
    throw "Repository working tree is not clean before promotion."
}

$targetRelease = Join-Path $ReleasesRoot $originMain
$rollbackPath = Join-Path $ReleasesRoot $RollbackRelease

# Preflight rollback release AND its installer before any mutation.
$rollbackInstallerPath = Join-Path $rollbackPath "deploy\windows\install-aether-services.ps1"
if (-not (Test-Path -LiteralPath $rollbackInstallerPath -PathType Leaf)) {
    throw "Rollback installer missing (preflight failed): $rollbackInstallerPath"
}
if (Test-Path -LiteralPath $targetRelease -PathType Container) {
    # Retry-safe: a prior failed promotion may have left a published-but-unproven
    # release. Reuse it only if it carries matching release metadata; otherwise
    # fail with a clear instruction (never silently overwrite an immutable path).
    $metaPath = Join-Path $targetRelease "AETHER_RELEASE.json"
    if (Test-Path -LiteralPath $metaPath -PathType Leaf) {
        $meta = Get-Content -LiteralPath $metaPath -Raw | ConvertFrom-Json
        if ($meta.target_sha -eq $originMain) {
            $reusedExisting = $true
        }
        else {
            throw "Existing release metadata target_sha mismatch: $($meta.target_sha)"
        }
    }
    else {
        throw "Target release already exists without release metadata (partial publish); remove it before retry: $targetRelease"
    }
}
else {
    $reusedExisting = $false
}

# DACL precondition of AETHER_HOME before reconcile.
if (-not $SkipAclCheck) {
    Assert-ProtectedAcl -Path $AetherHome -IsContainer $true -Label "AETHER_HOME(pre)"
}

$receipt = [ordered]@{
    schema = "aether.release-promotion.v4"
    event = "aether.release.promoted"
    promoted_at = (Get-Date).ToUniversalTime().ToString("o")
    target_sha = $originMain
    expected_target_sha = $ExpectedTargetSha
    release_path = $targetRelease
    aether_home = $AetherHome
    rollback_release = $RollbackRelease
    rollback_path = $rollbackPath
    reused_existing = $reusedExisting
    published_this_run = $false
    partial_publish_removed = $false
    reconciled = @()
    running_paths_proven = $false
    service_mutation_started = $false
    restart_proven = $false
    worker_deactivated = $false
    rollback_triggered = $false
    rollback_reason = $null
    rollback_running_path_proven = $false
    rollback_health_proven = $false
    rollback_acl_proven = $false
    rollback_manifest_proven = $false
    rollback_error = $null
    rollback_proven = $false
    success = $false
    error = $null
    failure_phase = $null
}

function Assert-ReleaseVenv {
    param([Parameter(Mandatory = $true)][string]$ReleasePath)

    $venvDir = Join-Path $ReleasePath ".venv"
    if (-not (Test-Path -LiteralPath $venvDir -PathType Container)) {
        throw "Release venv does not exist at $venvDir. Run Build-ReleaseVenv first."
    }
    $marker = Join-Path $venvDir ".aether-venv.json"
    if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) {
        throw "Release venv at $venvDir has no provenance marker $marker."
    }
    try {
        $meta = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
        if ([string]$meta.release_sha -ne $originMain) {
            throw "Release venv was built for $($meta.release_sha), not $originMain."
        }
        if ([string]$meta.livekit_agents -ne "1.6.9") {
            throw "Release venv has wrong livekit-agents version: $($meta.livekit_agents)."
        }
    }
    catch {
        throw "Assert-ReleaseVenv failed: $_"
    }
    $venvPython = Join-Path $venvDir "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        throw "Release venv python not found: $venvPython"
    }
    # Verify the INSTALLED package versions (marker alone is insufficient; the
    # environment may differ from the marker).
    $versions = & $venvPython -c "import importlib.metadata; print(importlib.metadata.version('livekit-agents')); print(importlib.metadata.version('livekit-api')); print(importlib.metadata.version('livekit-plugins-silero'))" 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Release venv LiveKit SDK version query failed: $versions"
    }
    $expected = @("1.6.9", "1.2.0", "1.6.9")
    $got = @($versions -split "`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    for ($i = 0; $i -lt $expected.Count; $i++) {
        if ($got[$i] -ne $expected[$i]) {
            throw "Release venv package version mismatch at index ${i}: expected $($expected[$i]), got $($got[$i])."
        }
    }
    $imports = & $venvPython -c "import livekit.agents; import livekit.api; import livekit.plugins.silero; print('imports OK')" 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Release venv LiveKit SDK import failed: $imports"
    }
    Write-Host "Release venv verified: $imports ($(($got -join ',')))"
}

function Build-ReleaseVenv {
    param(
        [Parameter(Mandatory = $true)][string]$ReleasePath,
        [Parameter(Mandatory = $true)][string]$TargetSha
    )

    $venvDir = Join-Path $ReleasePath ".venv"
    if (Test-Path -LiteralPath $venvDir -PathType Container) {
        # An existing venv is only accepted if its metadata proves it was built
        # for this exact release tree. Otherwise rebuild.
        $marker = Join-Path $venvDir ".aether-venv.json"
        $accept = $false
        if (Test-Path -LiteralPath $marker -PathType Leaf) {
            try {
                $meta = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
                $accept = ([string]$meta.release_sha -eq $TargetSha)
            }
            catch {
                $accept = $false
            }
        }
        if ($accept) {
            Write-Host "Release venv already verified for $TargetSha at $venvDir; skipping creation."
            return
        }
        Remove-Item -LiteralPath $venvDir -Recurse -Force -ErrorAction Stop
    }
    $python = $PythonPath
    if (-not $python -or -not (Test-Path -LiteralPath $python -PathType Leaf)) {
        $python = (Get-Command python.exe -ErrorAction Stop).Source
    }
    Write-Host "Building release venv at $venvDir using $python"
    try {
        & $python -m venv $venvDir
        if ($LASTEXITCODE -ne 0) { throw "venv creation failed (exit $LASTEXITCODE)" }
        $venvPython = Join-Path $venvDir "Scripts\python.exe"
        if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
            throw "venv python not found after creation: $venvPython"
        }
        & $venvPython -m pip install --upgrade pip --quiet
        # Non-editable install: the packages are COPIED into the venv so the
        # venv is self-contained and immutable for this release.
        & $venvPython -m pip install --no-cache-dir "$ReleasePath\aether-core" "$ReleasePath\aether-tools" "$ReleasePath\aether-gateway[livekit]" --quiet
        if ($LASTEXITCODE -ne 0) { throw "pip install failed (exit $LASTEXITCODE)" }
        # Verify the SDK is importable and the pinned versions are correct.
        $verify = (& $venvPython -c "import importlib.metadata; print(importlib.metadata.version('livekit-agents')); print(importlib.metadata.version('livekit-api')); print(importlib.metadata.version('livekit-plugins-silero'))") -join ";"
        if ($LASTEXITCODE -ne 0) { throw "venv verification failed: $verify" }
        # Write the provenance marker so future promotions can trust this venv.
        $marker = Join-Path $venvDir ".aether-venv.json"
        $meta = [ordered]@{
            schema = "aether.release-venv.v1"
            release_sha = $TargetSha
            built_at = (Get-Date).ToUniversalTime().ToString("o")
            python = $python
            livekit_agents = "1.6.9"
            livekit_api = "1.2.0"
            livekit_plugins_silero = "1.6.9"
        }
        $meta | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $marker -Encoding UTF8
        Write-Host "Release venv built and verified: $verify"
    }
    catch {
        throw "Build-ReleaseVenv failed: $_"
    }
}

function Invoke-Installer {
    param(
        [Parameter(Mandatory = $true)][string]$ReleasePath,
        [Parameter(Mandatory = $true)][string]$TargetSha,
        [Parameter(Mandatory = $true)][string]$Phase,
        [switch]$IncludeSenseWorker
    )

    # Always drive the CURRENT (safe) installer from the target release, never
    # a legacy /inheritance:e installer from a stale rollback folder.
    $installer = Join-Path $targetRelease "deploy\windows\install-aether-services.ps1"
    $hook = $env:AETHER_PROMO_INSTALL_CMD
    if ($hook) {
        if (-not (Test-Path -LiteralPath $hook -PathType Leaf)) {
            throw "AETHER_PROMO_INSTALL_CMD not found: $hook"
        }
        # Only pass -IncludeSenseWorker when the seam declares support (test
        # seams predate the worker and would error on an unknown switch).
        $hookText = Get-Content -LiteralPath $hook -Raw -ErrorAction SilentlyContinue
        if ($IncludeSenseWorker -and $null -ne $hookText -and $hookText.Contains("IncludeSenseWorker")) {
            & $hook -ReleasePath $ReleasePath -TargetSha $TargetSha -AetherHome $AetherHome -HostAddress $HostAddress -Port ([string]$Port) -Phase $Phase -IncludeSenseWorker
        }
        else {
            & $hook -ReleasePath $ReleasePath -TargetSha $TargetSha -AetherHome $AetherHome -HostAddress $HostAddress -Port ([string]$Port) -Phase $Phase
        }
        if ($LASTEXITCODE -ne 0) {
            throw "installer hook failed (phase=$Phase, exit=$LASTEXITCODE)"
        }
        return
    }
    if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {
        throw "Installer missing: $installer"
    }
    $installerArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", $installer,
        "-ReleasePath", $ReleasePath,
        "-TargetSha", $TargetSha,
        "-AetherHome", $AetherHome,
        "-HostAddress", $HostAddress,
        "-Port", [string]$Port
    )
    if ($PythonPath) {
        $installerArgs += @("-PythonPath", $PythonPath)
    }
    if ($IncludeSenseWorker) {
        $installerArgs += @("-InstallSenseWorker")
    }
    & powershell.exe @installerArgs | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "install-aether-services reconcile failed (phase=$Phase, exit=$LASTEXITCODE)"
    }
}

function Restart-GatewayServices {
    # Restart failures are NEVER swallowed. Either the restart hook fails the
    # run or the real Get-Service/Restart-Service errors propagate.
    param(
        [Parameter(Mandatory = $true)][string]$ReleasePath,
        [switch]$IncludeSenseWorker
    )

    $hook = $env:AETHER_PROMO_RESTART_CMD
    if ($hook -and (Test-Path -LiteralPath $hook -PathType Leaf)) {
        & $hook -ReleasePath $ReleasePath
        if ($LASTEXITCODE -ne 0) {
            throw "service restart hook failed (exit $LASTEXITCODE)"
        }
        return
    }
    $serviceNames = @("AetherGateway")
    if ($IncludeSenseWorker) {
        $serviceNames += "AetherSenseWorker"
    }
    $serviceNames += "AetherWatchdog"
    foreach ($name in $serviceNames) {
        $svc = Get-Service -Name $name -ErrorAction Stop
        if ($null -eq $svc) {
            throw "Service '$name' missing; cannot restart for promotion."
        }
        Restart-Service -Name $name -Force -ErrorAction Stop | Out-Null
    }
    Start-Sleep -Seconds 2
}

function Test-Health {
    $hook = $env:AETHER_PROMO_HEALTH_CMD
    if ($hook -and (Test-Path -LiteralPath $hook -PathType Leaf)) {
        $out = (& $hook | Out-String).Trim()
        return ($out -match '(?i)^true')
    }
    for ($i = 0; $i -lt $HealthAttempts; $i++) {
        Start-Sleep -Seconds 2
        try {
            $resp = Invoke-WebRequest -Uri "http://$HostAddress`:$Port/health" -TimeoutSec $HealthTimeoutSeconds -UseBasicParsing
            if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 300) {
                return $true
            }
        }
        catch {
        }
    }
    return $false
}

function Test-RollbackManifest {
    # Live service provenance after reconcile: the service-manifest written by
    # the installer must be rebound to the rollback release. The static
    # AETHER_RELEASE.json of the rollback folder is NOT sufficient evidence.
    $manifestPath = Join-Path $AetherHome "services\service-manifest.json"
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { return $false }
    try {
        $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        return (
            ([string]$manifest.release_path -eq $rollbackPath) -and
            ([string]$manifest.target_sha -eq $RollbackRelease)
        )
    }
    catch {
        return $false
    }
}

function Invoke-UniversalRollback {
    param([string]$Reason)

    $script:rollbackAttempted = $true
    $receipt.rollback_triggered = $true
    $receipt.rollback_reason = $Reason
    $receipt.rollback_proven = $false

    $safeInstaller = Join-Path $targetRelease "deploy\windows\install-aether-services.ps1"
    if (-not (Test-Path -LiteralPath $safeInstaller -PathType Leaf)) {
        $receipt.rollback_error = "Safe installer missing for fail-closed rollback: $safeInstaller"
        throw $receipt.rollback_error
    }

    # Worker rollback compatibility: the rollback release (e.g. 956a48a) predates
    # -SecretEnvPath support in aether-service-runner.ps1. Re-pointing the worker
    # to that runner would crash-loop (no secret injection). The honest choice is
    # to stop + set the worker to Manual and reconcile only Gateway/Watchdog, then
    # record worker_deactivated=true so the outcome is explicit, not a hang.
    $rollbackRunner = Join-Path $rollbackPath "deploy\windows\aether-service-runner.ps1"
    $rollbackSupportsSecretEnv = $false
    if (Test-Path -LiteralPath $rollbackRunner -PathType Leaf) {
        $rollbackRunnerText = Get-Content -LiteralPath $rollbackRunner -Raw -ErrorAction SilentlyContinue
        $rollbackSupportsSecretEnv = ($null -ne $rollbackRunnerText -and $rollbackRunnerText.Contains('$SecretEnvPath'))
    }
    $workerDeactivated = $false
    if ($IncludeSenseWorker -and -not $rollbackSupportsSecretEnv) {
        $workerSvc = Get-Service -Name "AetherSenseWorker" -ErrorAction SilentlyContinue
        if ($null -ne $workerSvc -and $workerSvc.Status -ne [System.ServiceProcess.ServiceControllerStatus]::Stopped) {
            Stop-Service -Name "AetherSenseWorker" -Force -ErrorAction Stop | Out-Null
        }
        Set-Service -Name "AetherSenseWorker" -StartupType Manual -ErrorAction SilentlyContinue
        $workerDeactivated = $true
        $receipt.worker_deactivated = $true
    }

    # Reconcile only the services the rollback release can safely host.
    $rollbackIncludeWorker = ($IncludeSenseWorker -and $rollbackSupportsSecretEnv)
    Invoke-Installer -ReleasePath $rollbackPath -TargetSha $RollbackRelease -Phase "rollback" -IncludeSenseWorker:$rollbackIncludeWorker
    Restart-GatewayServices -ReleasePath $rollbackPath -IncludeSenseWorker:$rollbackIncludeWorker
    $receipt.restart_proven = $true

    # Every postcondition is observed independently, then aggregated. The
    # aggregate may only become true when ALL of them hold.
    $runningPathOk = $false
    try {
        $rollbackBoundNames = @("AetherGateway", "AetherWatchdog")
        if ($rollbackIncludeWorker) {
            $rollbackBoundNames += "AetherSenseWorker"
        }
        $runningPathOk = (Confirm-ServiceBoundToRelease -Names $rollbackBoundNames -ReleasePath $rollbackPath)
    }
    catch {
        $runningPathOk = $false
    }
    $receipt.rollback_running_path_proven = $runningPathOk

    $healthOk = Test-Health
    $receipt.rollback_health_proven = $healthOk

    $aclOk = $true
    if (-not $SkipAclCheck) {
        try {
            Assert-ProtectedAcl -Path $AetherHome -IsContainer $true -Label "AETHER_HOME(post-rollback)"
            $aclOk = $true
        }
        catch {
            $aclOk = $false
        }
    }
    $receipt.rollback_acl_proven = $aclOk

    $manifestOk = Test-RollbackManifest
    $receipt.rollback_manifest_proven = $manifestOk

    $proven = ($runningPathOk -and $healthOk -and $aclOk -and $manifestOk)
    $receipt.rollback_proven = $proven
    if (-not $proven) {
        $failed = @()
        if (-not $runningPathOk) { $failed += "running_path" }
        if (-not $healthOk) { $failed += "health" }
        if (-not $aclOk) { $failed += "acl" }
        if (-not $manifestOk) { $failed += "live_manifest" }
        $receipt.rollback_error = "Rollback postconditions failed after reconcile: $($failed -join ', ')"
    }
    return $proven
}

$serviceMutationStarted = $false
$rollbackAttempted = $false

# -SkipReleaseVenv is a TEST-ONLY escape hatch (seams build no venv). Production
# must never set it: a real promotion always builds/verifies the release venv.
if ($SkipReleaseVenv -and -not $AllowNonElevated) {
    throw "-SkipReleaseVenv is only permitted in test seams (-AllowNonElevated). Refusing to run in production."
}

try {
    # ---- Stage into a temporary directory + durable metadata, then publish. ----
    if (-not $reusedExisting) {
        $staging = Join-Path $ReleasesRoot ".staging-$originMain-$(Get-Random)"
        New-Item -ItemType Directory -Force -Path $staging | Out-Null
        $archive = Join-Path $ReleasesRoot ".archive-$originMain-$(Get-Random).tar"
        $archiveExit = Invoke-Git -GitArgs @("-C", $RepoPath, "archive", "--format=tar", "--output=$archive", $originMain)
        if ($archiveExit -ne 0) {
            throw "git archive failed (exit $archiveExit)"
        }
        tar -xf $archive -C $staging
        if ($LASTEXITCODE -ne 0) {
            throw "tar extraction failed (exit $LASTEXITCODE)"
        }
        Remove-Item -LiteralPath $archive -Force

        # Durable release metadata (the extraction has no .git; do NOT rev-parse it).
        $treeResult = Invoke-GitCapture -GitArgs @("-C", $RepoPath, "rev-parse", "$originMain^{tree}")
        $tree = $treeResult.Output.Trim()
        if ($treeResult.ExitCode -ne 0) {
            throw "unable to resolve target tree hash"
        }
        $releaseMeta = [ordered]@{
            schema = "aether.release.v1"
            target_sha = $originMain
            target_tree = $tree
            staged_at = (Get-Date).ToUniversalTime().ToString("o")
            aether_home = $AetherHome
        }
        $releaseMeta | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $staging "AETHER_RELEASE.json") -Encoding UTF8

        # Build the release-specific venv BEFORE the atomic publish so a failed
        # build never leaves a published-but-broken release behind.
        if (-not $SkipReleaseVenv) {
            Build-ReleaseVenv -ReleasePath $staging -TargetSha $originMain
        }

        # Atomic publish: rename staging -> final.
        Move-Item -LiteralPath $staging -Destination $targetRelease -ErrorAction Stop
        $receipt.published_this_run = $true
    }

    # --- Reconcile services to the new release. ---
    # The release venv must be verified BEFORE any service mutation, both for a
    # freshly published release and a reused one. -SkipReleaseVenv is a TEST-ONLY
    # escape hatch (seams build no venv); production never sets it.
    if (-not $SkipReleaseVenv) {
        Assert-ReleaseVenv -ReleasePath $targetRelease
    }
    $serviceMutationStarted = $true
    $receipt.service_mutation_started = $true
    Invoke-Installer -ReleasePath $targetRelease -TargetSha $originMain -Phase "promote" -IncludeSenseWorker:$IncludeSenseWorker
    $receipt.reconciled = @("AetherGateway", "AetherWatchdog")
    if ($IncludeSenseWorker) {
        $receipt.reconciled += "AetherSenseWorker"
    }

    # --- Restart in governed order, then prove live processes bind the release. ---
    Restart-GatewayServices -ReleasePath $targetRelease -IncludeSenseWorker:$IncludeSenseWorker
    $receipt.restart_proven = $true

    $boundNames = @("AetherGateway", "AetherWatchdog")
    if ($IncludeSenseWorker) {
        $boundNames += "AetherSenseWorker"
    }
    Confirm-ServiceBoundToRelease -Names $boundNames -ReleasePath $targetRelease | Out-Null
    $receipt.running_paths_proven = $true

    # Health gate against the exact target release.
    $healthy = Test-Health
    if (-not $healthy) {
        # Fail-closed universal rollback: safe installer against rollback
        # release, restart, live running-path proof, health, DACL, manifest.
        Invoke-UniversalRollback -Reason "health_failure_after_promote" | Out-Null
        throw "Gateway health failed after promotion; fail-closed rollback proven=$($receipt.rollback_proven)"
    }

    # Re-assert the protected AETHER_HOME DACL AFTER reconciliation.
    if (-not $SkipAclCheck) {
        Assert-ProtectedAcl -Path $AetherHome -IsContainer $true -Label "AETHER_HOME(post)"
    }
    $receipt.success = $true
}
catch {
    $receipt.failure_phase = "promote"
    $receipt.error = $_.Exception.Message

    # Universal rollback envelope: every failure after service configuration
    # mutation must reconcile back to the rollback release. The target release
    # is NEVER deleted once services may reference it.
    if ($serviceMutationStarted -and -not $rollbackAttempted) {
        try {
            Invoke-UniversalRollback -Reason "post_mutation_failure" | Out-Null
        }
        catch {
            $receipt.rollback_error = $_.Exception.Message
            $receipt.rollback_proven = $false
            $rollbackAttempted = $true
        }
    }

    # Only a publish that never touched services may be removed (retry-safe).
    if (-not $serviceMutationStarted -and $receipt.published_this_run) {
        if (Test-Path -LiteralPath $targetRelease -PathType Container) {
            Remove-Item -LiteralPath $targetRelease -Recurse -Force -ErrorAction SilentlyContinue
            $receipt.partial_publish_removed = $true
        }
    }

    $receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $AetherHome "services\release-promotion-failure.json") -Encoding UTF8
    throw
}

$receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $AetherHome "services\release-promotion.json") -Encoding UTF8
$receipt | ConvertTo-Json -Depth 8
