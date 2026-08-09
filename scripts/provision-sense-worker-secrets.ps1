[CmdletBinding()]
param(
    [string]$AetherHome = "C:\ProgramData\Aether",
    [string]$SourceEnvPath = ""
)

<#
    Provision the canonical senses LiveKit secret env file (read by the service
    runner for BOTH the Gateway and the Sense Worker).

    Design (per ChatGPT review 2026-08-09):
    - Secrets live OUTSIDE the immutable release, in AETHER_HOME\secrets\senses-livekit.env.
    - The source of truth is a PROTECTED env file OUTSIDE the repo, passed via
      -SourceEnvPath (e.g. C:\ProgramData\Aether\secrets\source-livekit.env).
      Secrets are NEVER accepted as command-line arguments and never need to be
      stored in the dev tree (aether-core/.env).
    - The file + secrets directory have a protected DACL (SYSTEM + Administrators
      only, no inheritance) AND an explicit owner (Administrators). Exact ACL and
      owner are verified after writing, before and after the atomic replace.
    - The runner injects a role-scoped allowlist into each service process.

    Usage:
      .\provision-sense-worker-secrets.ps1 -SourceEnvPath C:\ProgramData\Aether\secrets\source-livekit.env
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run this provisioning script from an elevated PowerShell session."
    }
}

function New-ProtectedFileAcl {
    $acl = New-Object System.Security.AccessControl.FileSecurity
    $acl.SetAccessRuleProtection($true, $false)
    $inherit = [System.Security.AccessControl.InheritanceFlags]::None
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

function Assert-ExactProtectedAcl {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [bool]$IsContainer = $false,
        [string]$Label = $Path
    )
    $acl = Get-Acl -LiteralPath $Path
    if (-not $acl.AreAccessRulesProtected) {
        throw "$Label has unprotected DACL (inheritance enabled)."
    }
    $fullControl = [System.Security.AccessControl.FileSystemRights]::FullControl
    $expected = @{ "S-1-5-18" = $false; "S-1-5-32-544" = $false }
    foreach ($rule in $acl.Access) {
        if ($rule.AccessControlType -eq "Deny") {
            throw "$Label has a Deny ACE (unexpected)."
        }
        $sid = $rule.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
        if ($sid -ne "S-1-5-18" -and $sid -ne "S-1-5-32-544") {
            throw "$Label has unexpected ACE for $sid."
        }
        if (($rule.FileSystemRights -band $fullControl) -ne $fullControl) {
            throw "$Label grants $sid rights other than FullControl."
        }
        $expected[$sid] = $true
        if (-not $IsContainer -and $rule.InheritanceFlags -ne [System.Security.AccessControl.InheritanceFlags]::None) {
            throw "$Label has an inherited-flag ACE for $sid (file must have InheritanceFlags=None)."
        }
    }
    foreach ($sid in $expected.Keys) {
        if (-not $expected[$sid]) {
            throw "$Label is missing required SID $sid."
        }
    }
    if ($acl.Owner -notmatch "(S-1-5-18|S-1-5-32-544|NT AUTHORITY\\SYSTEM|BUILTIN\\Administrators)") {
        throw "$Label owner is not SYSTEM or Administrators: $($acl.Owner)"
    }
}

Assert-Administrator

$secretsDir = Join-Path $AetherHome "secrets"
$target = Join-Path $secretsDir "senses-livekit.env"

# --- Gather values ONLY from a protected source env file outside the repo. ---
# The source file must live outside the dev tree so rotated credentials do not
# need to be stored in aether-core/.env. It is protected (SYSTEM + Administrators,
# no inheritance) and validated for reparse points before being read.
if (-not $SourceEnvPath) {
    throw "Missing -SourceEnvPath. Point it at a protected env file outside the repo (e.g. C:\ProgramData\Aether\secrets\source-livekit.env)."
}
$dotEnv = (Resolve-Path -LiteralPath $SourceEnvPath -ErrorAction Stop).Path
$srcInfo = Get-Item -LiteralPath $dotEnv -Force -ErrorAction Stop
if ($srcInfo.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
    throw "SourceEnvPath $dotEnv is a reparse point. Refusing to read."
}
Assert-ExactProtectedAcl -Path $dotEnv -Label "SourceEnvPath $dotEnv"
$envMap = @{}
foreach ($raw in Get-Content -LiteralPath $dotEnv -Encoding UTF8) {
    $line = $raw.Trim()
    if (-not $line -or $line.StartsWith("#") -or "=" -notin $line) { continue }
    $key, $value = $line.Split("=", 2)
    $envMap[$key.Trim()] = $value.Trim()
}

$required = @("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "AETHER_SENSE_WORKER_TOKEN", "LIVEKIT_AGENT_NAME")
foreach ($key in $required) {
    if (-not $envMap[$key]) {
        throw "Missing required value for $key in $dotEnv. Cannot provision."
    }
    if ($envMap[$key] -match "[\r\n]") {
        throw "Malformed value for $key (newline) in $dotEnv. Refusing to write."
    }
}

New-Item -ItemType Directory -Force -Path $secretsDir | Out-Null
# Protect the secrets directory (SYSTEM + Administrators only, no inheritance)
# and set its owner to Administrators.
$dirAcl = Get-Acl -LiteralPath $secretsDir
if (-not $dirAcl.AreAccessRulesProtected) {
    $protectedDirAcl = New-Object System.Security.AccessControl.DirectorySecurity
    $protectedDirAcl.SetAccessRuleProtection($true, $false)
    $dirInherit = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
        [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
    foreach ($sid in @("S-1-5-18", "S-1-5-32-544")) {
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            (New-Object System.Security.Principal.SecurityIdentifier $sid),
            [System.Security.AccessControl.FileSystemRights]::FullControl,
            $dirInherit,
            [System.Security.AccessControl.PropagationFlags]::None,
            [System.Security.AccessControl.AccessControlType]::Allow
        )
        $protectedDirAcl.AddAccessRule($rule)
    }
    [System.IO.Directory]::SetAccessControl($secretsDir, $protectedDirAcl)
}
$adminsSid = New-Object System.Security.Principal.SecurityIdentifier "S-1-5-32-544"
$adminsAcct = $adminsSid.Translate([System.Security.Principal.NTAccount])
$dirOwnerAcl = Get-Acl -LiteralPath $secretsDir
$dirOwnerAcl.SetOwner($adminsAcct)
[System.IO.Directory]::SetAccessControl($secretsDir, $dirOwnerAcl)
Assert-ExactProtectedAcl -Path $secretsDir -IsContainer $true -Label "secrets directory"

$content = @(
    "LIVEKIT_URL=$($envMap['LIVEKIT_URL'])"
    "LIVEKIT_API_KEY=$($envMap['LIVEKIT_API_KEY'])"
    "LIVEKIT_API_SECRET=$($envMap['LIVEKIT_API_SECRET'])"
    "AETHER_SENSE_WORKER_TOKEN=$($envMap['AETHER_SENSE_WORKER_TOKEN'])"
    "LIVEKIT_AGENT_NAME=$($envMap['LIVEKIT_AGENT_NAME'])"
) -join "`r`n"

# Atomic replace: write to a unique protected temp file in the SAME directory,
# verify, then File.Replace (a single atomic Win32 replacement that also moves
# the temp's ACL to the target). Cleanup in finally so no partial temp remains.
$tempPath = Join-Path $secretsDir ("senses-livekit.env.tmp." + [System.Guid]::NewGuid().ToString("N"))
$replaced = $false
try {
    [System.IO.File]::WriteAllText($tempPath, $content + "`r`n", (New-Object System.Text.UTF8Encoding($false)))
    $acl = New-ProtectedFileAcl
    [System.IO.File]::SetAccessControl($tempPath, $acl)
    $tempOwnerAcl = Get-Acl -LiteralPath $tempPath
    $tempOwnerAcl.SetOwner($adminsAcct)
    [System.IO.File]::SetAccessControl($tempPath, $tempOwnerAcl)

    # Exact verification BEFORE the atomic replace.
    Assert-ExactProtectedAcl -Path $tempPath -Label "temp secret file"

    $found = Get-Content -LiteralPath $tempPath -Encoding UTF8
    $actual = @{}
    foreach ($raw in $found) {
        $line = $raw.Trim()
        if (-not $line -or $line.StartsWith("#") -or "=" -notin $line) { continue }
        $key, $value = $line.Split("=", 2)
        $actual[$key.Trim()] = $value.Trim()
    }
    $count = $required | Where-Object { $actual[$_] } | Measure-Object
    if ($count.Count -lt $required.Count) {
        throw "Provisioned temp secret file is missing expected keys."
    }

    # Single atomic replace. File.Replace preserves the DACL of the DESTINATION
    # (the existing target), not the temp. So we verify the existing target's
    # DACL pre-replace, then re-apply the protected ACL post-replace.
    if (Test-Path -LiteralPath $target -PathType Leaf) {
        Assert-ExactProtectedAcl -Path $target -Label "existing target secret file"
        [System.IO.File]::Replace($tempPath, $target, $null)
        $replaced = $true
        # Re-apply the protected ACL to the target (File.Replace preserved the
        # old DACL; enforce the canonical one).
        $acl = New-ProtectedFileAcl
        [System.IO.File]::SetAccessControl($target, $acl)
        $ownerAcl = Get-Acl -LiteralPath $target
        $ownerAcl.SetOwner($adminsAcct)
        [System.IO.File]::SetAccessControl($target, $ownerAcl)
    }
    else {
        [System.IO.File]::Move($tempPath, $target)
        $replaced = $true
    }

    # Final exact verification AFTER the replace.
    Assert-ExactProtectedAcl -Path $target -Label "final secret file"
}
finally {
    if (-not $replaced -and (Test-Path -LiteralPath $tempPath -PathType Leaf)) {
        Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
    }
}

$finalAcl = Get-Acl -LiteralPath $target
[pscustomobject]@{
    status = "ok"
    secret_env_path = $target
    keys = $required
    dacl_protected = $finalAcl.AreAccessRulesProtected
    owner = $finalAcl.Owner
} | ConvertTo-Json -Depth 4
