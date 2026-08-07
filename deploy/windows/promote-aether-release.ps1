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
    [switch]$Start,
    [switch]$SkipValidate
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

Assert-Administrator

if (-not (Test-Path -LiteralPath $RepoPath -PathType Container)) {
    throw "Repo path not found: $RepoPath"
}
if (-not (Test-Path -LiteralPath $AetherHome -PathType Container)) {
    throw "AETHER_HOME not found: $AetherHome"
}

# ---- Resolve exact target SHA (source authority) ----------------------------
git -C $RepoPath fetch origin main 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "git fetch origin main failed"
}
$originMain = (git -C $RepoPath rev-parse origin/main 2>$null | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $originMain -notmatch '^[0-9a-f]{40}$') {
    throw "Unable to resolve origin/main SHA"
}
if ($ExpectedTargetSha -ne $originMain) {
    throw "Expected-target-SHA guard failed: requested $ExpectedTargetSha, origin/main = $originMain"
}
$dirty = @(git -C $RepoPath status --porcelain 2>$null)
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
Assert-ProtectedAcl -Path $AetherHome -IsContainer $true -Label "AETHER_HOME(pre)"

$receipt = [ordered]@{
    schema = "aether.release-promotion.v2"
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
    reconciled = @()
    running_paths_proven = $false
    rollback_triggered = $false
    rollback_proven = $false
    success = $false
}

try {
    # ---- Stage into a temporary directory + durable metadata, then publish. ----
    if (-not $reusedExisting) {
        $staging = Join-Path $ReleasesRoot ".staging-$originMain-$(Get-Random)"
        New-Item -ItemType Directory -Force -Path $staging | Out-Null
        $archive = Join-Path $ReleasesRoot ".archive-$originMain-$(Get-Random).tar"
        git -C $RepoPath archive --format=tar --output=$archive $originMain 2>$null
        if ($LASTEXITCODE -ne 0) {
            throw "git archive failed (exit $LASTEXITCODE)"
        }
        tar -xf $archive -C $staging
        if ($LASTEXITCODE -ne 0) {
            throw "tar extraction failed (exit $LASTEXITCODE)"
        }
        Remove-Item -LiteralPath $archive -Force

        # Durable release metadata (the extraction has no .git; do NOT rev-parse it).
        $tree = git -C $RepoPath rev-parse "$originMain^{tree}" 2>$null
        if ($LASTEXITCODE -ne 0) {
            throw "unable to resolve target tree hash"
        }
        $releaseMeta = [ordered]@{
            schema = "aether.release.v1"
            target_sha = $originMain
            target_tree = ($tree | Out-String).Trim()
            staged_at = (Get-Date).ToUniversalTime().ToString("o")
            aether_home = $AetherHome
        }
        $releaseMeta | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $staging "AETHER_RELEASE.json") -Encoding UTF8

        # Atomic publish: rename staging -> final.
        Move-Item -LiteralPath $staging -Destination $targetRelease -ErrorAction Stop
        $receipt.published_this_run = $true
    }

    # --- Reconcile services to the new release. ---
    $installer = Join-Path $targetRelease "deploy\windows\install-aether-services.ps1"
    $installerArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", $installer,
        "-ReleasePath", $targetRelease,
        "-TargetSha", $originMain,
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

    # --- Restart in governed order, then prove running paths bind new release. ---
    if ($Start) {
        foreach ($name in @("AetherGateway", "AetherWatchdog")) {
            $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
            if ($null -ne $svc) {
                Restart-Service -Name $name -Force -ErrorAction Stop
            }
        }
        Start-Sleep -Seconds 2

        $runningPathOk = Confirm-ServiceBoundToRelease -Names @("AetherGateway", "AetherWatchdog") -ReleasePath $targetRelease
        $receipt.running_paths_proven = $true

        # Health gate against the Exact target release.
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
            # --- Fail-closed rollback: use the CURRENT (safe) installer against
            #      the rollback release so the old /inheritance:e cannot run. ---
            $receipt.rollback_triggered = $true
            $safeInstaller = Join-Path $targetRelease "deploy\windows\install-aether-services.ps1"
            if (-not (Test-Path -LiteralPath $safeInstaller -PathType Leaf)) {
                throw "Safe installer missing for fail-closed rollback: $safeInstaller"
            }
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $safeInstaller -ReleasePath $rollbackPath -AetherHome $AetherHome -HostAddress $HostAddress -Port $Port | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "Rollback reconcile failed (exit $LASTEXITCODE)"
            }
            foreach ($name in @("AetherGateway", "AetherWatchdog")) {
                $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
                if ($null -ne $svc) {
                    Restart-Service -Name $name -Force -ErrorAction Stop
                }
            }
            Start-Sleep -Seconds 2
            Confirm-ServiceBoundToRelease -Names @("AetherGateway", "AetherWatchdog") -ReleasePath $rollbackPath
            $ok = $false
            for ($i = 0; $i -lt $HealthAttempts; $i++) {
                Start-Sleep -Seconds 2
                try {
                    $resp = Invoke-WebRequest -Uri "http://$HostAddress`:$Port/health" -TimeoutSec $HealthTimeoutSeconds -UseBasicParsing
                    if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 300) {
                        $ok = $true
                        break
                    }
                }
                catch {
                }
            }
            $receipt.rollback_proven = $ok
            Assert-ProtectedAcl -Path $AetherHome -IsContainer $true -Label "AETHER_HOME(post-rollback)"
            throw "Gateway health failed after promotion; fail-closed rollback to $rollbackPath proven=$ok"
        }
    }

    # Re-assert the protected AETHER_HOME DACL AFTER reconciliation.
    Assert-ProtectedAcl -Path $AetherHome -IsContainer $true -Label "AETHER_HOME(post)"
    $receipt.success = $true
}
catch {
    if ($receipt.published_this_run -and (Test-Path -LiteralPath $targetRelease -PathType Container)) {
        # A failed promotion that we published ourselves must not leave a partial
        # immutable release that blocks retry; remove it so the run is retry-safe.
        Remove-Item -LiteralPath $targetRelease -Recurse -Force -ErrorAction SilentlyContinue
    }
    $receipt.failure_phase = "promote"
    $receipt.error = $_.Exception.Message
    $receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $AetherHome "services\release-promotion-failure.json") -Encoding UTF8
    throw
}

$receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $AetherHome "services\release-promotion.json") -Encoding UTF8
$receipt | ConvertTo-Json -Depth 8