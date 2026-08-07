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
    [switch]$SkipValidate
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
#   code decides success/failure. Default: real installer invocation.
# AETHER_PROMO_HEALTH_CMD    : path to a .ps1 printing True/False as the
#   health probe result. Default: real HTTP probe on HostAddress:Port/health.
# AETHER_PROMO_SERVICE_CMD   : path to a .ps1 invoked with -ReleasePath that
#   prints a JSON array of observed services:
#   [ { name, running, path }, ... ]. Default: real Win32_Service/CIM lookup.
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

function Get-ServiceConfigBinPath {
    param([string]$Name)
    try {
        $service = Get-CimInstance Win32_Service -Filter "Name='$Name'"
        if ($null -eq $service) { return "" }
        return [string]$service.PathName
    }
    catch {
        return ""
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
            $running = $false
            $pathOk = $false
            if ($s.Count -eq 1) {
                try { $running = [bool]$s[0].running } catch { $running = $false }
                $pathOk = ([string]$s[0].path -match [regex]::Escape($ReleasePath))
            }
            if ($s.Count -ne 1 -or -not $running -or -not $pathOk) {
                $bad += "$name(payload path does not reference $ReleasePath or not Running)"
            }
        }
        if ($bad.Count -gt 0) {
            throw "Service running-path assertion failed: $($bad -join '; ')"
        }
        return $true
    }

    $bad = @()
    foreach ($name in $Names) {
        $path = Get-ServiceConfigBinPath -Name $name
        if (-not $path -or $path -notmatch [regex]::Escape($ReleasePath)) {
            $bad += "$name(payload path does not reference $ReleasePath)"
        }
        $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
        if ($null -eq $svc -or $svc.Status -ne "Running") {
            $bad += "$name(service not Running)"
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
    schema = "aether.release-promotion.v3"
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
    rollback_triggered = $false
    rollback_reason = $null
    rollback_running_path_proven = $false
    rollback_manifest_proven = $false
    rollback_error = $null
    rollback_proven = $false
    success = $false
    error = $null
    failure_phase = $null
}

function Invoke-Installer {
    param(
        [Parameter(Mandatory = $true)][string]$ReleasePath,
        [Parameter(Mandatory = $true)][string]$TargetSha,
        [Parameter(Mandatory = $true)][string]$Phase
    )

    # Always drive the CURRENT (safe) installer from the target release, never
    # a legacy /inheritance:e installer from a stale rollback folder.
    $installer = Join-Path $targetRelease "deploy\windows\install-aether-services.ps1"
    $hook = $env:AETHER_PROMO_INSTALL_CMD
    if ($hook) {
        if (-not (Test-Path -LiteralPath $hook -PathType Leaf)) {
            throw "AETHER_PROMO_INSTALL_CMD not found: $hook"
        }
        & $hook -ReleasePath $ReleasePath -TargetSha $TargetSha -AetherHome $AetherHome -HostAddress $HostAddress -Port ([string]$Port) -Phase $Phase
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
    & powershell.exe @installerArgs | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "install-aether-services reconcile failed (phase=$Phase, exit=$LASTEXITCODE)"
    }
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
    $metaPath = Join-Path $rollbackPath "AETHER_RELEASE.json"
    if (-not (Test-Path -LiteralPath $metaPath -PathType Leaf)) { return $false }
    try {
        $meta = Get-Content -LiteralPath $metaPath -Raw | ConvertFrom-Json
        return ([string]$meta.target_sha -eq $RollbackRelease)
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

    Invoke-Installer -ReleasePath $rollbackPath -TargetSha $RollbackRelease -Phase "rollback"
    foreach ($name in @("AetherGateway", "AetherWatchdog")) {
        $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
        if ($null -ne $svc) {
            Restart-Service -Name $name -Force -ErrorAction Stop | Out-Null
        }
    }
    Start-Sleep -Seconds 2

    $receipt.rollback_running_path_proven = (Confirm-ServiceBoundToRelease -Names @("AetherGateway", "AetherWatchdog") -ReleasePath $rollbackPath)
    $ok = Test-Health
    $receipt.rollback_proven = $ok
    if (-not $SkipAclCheck) {
        Assert-ProtectedAcl -Path $AetherHome -IsContainer $true -Label "AETHER_HOME(post-rollback)"
    }
    $receipt.rollback_manifest_proven = (Test-RollbackManifest)
    return $ok
}

$serviceMutationStarted = $false
$rollbackAttempted = $false

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

        # Atomic publish: rename staging -> final.
        Move-Item -LiteralPath $staging -Destination $targetRelease -ErrorAction Stop
        $receipt.published_this_run = $true
    }

    # --- Reconcile services to the new release. ---
    $serviceMutationStarted = $true
    $receipt.service_mutation_started = $true
    Invoke-Installer -ReleasePath $targetRelease -TargetSha $originMain -Phase "promote"
    $receipt.reconciled = @("AetherGateway", "AetherWatchdog")

    # --- Restart in governed order, then prove running paths bind new release. ---
    if ($Start) {
        foreach ($name in @("AetherGateway", "AetherWatchdog")) {
            $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
            if ($null -ne $svc) {
                Restart-Service -Name $name -Force -ErrorAction Stop | Out-Null
            }
        }
        Start-Sleep -Seconds 2

        Confirm-ServiceBoundToRelease -Names @("AetherGateway", "AetherWatchdog") -ReleasePath $targetRelease | Out-Null
        $receipt.running_paths_proven = $true

        # Health gate against the exact target release.
        $healthy = Test-Health
        if (-not $healthy) {
            # Fail-closed universal rollback: safe installer against rollback
            # release, restart, running-path proof, health, DACL, manifest.
            Invoke-UniversalRollback -Reason "health_failure_after_promote" | Out-Null
            throw "Gateway health failed after promotion; fail-closed rollback proven=$($receipt.rollback_proven)"
        }
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
