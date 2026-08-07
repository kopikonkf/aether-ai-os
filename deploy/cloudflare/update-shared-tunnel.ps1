[CmdletBinding()]
param(
    [string]$AetherHome = "C:\ProgramData\Aether",
    [string]$TunnelConfig = "C:\Users\aethers\.cloudflared\config.yml",
    [string]$CloudflaredPath = "",
    [string]$LocalOrigin = "http://localhost:8080",
    [string[]]$AetherHostnames = @("aethers.my.id", "www.aethers.my.id"),
    [string[]]$ProtectedHostnames = @("oc.aethers.my.id", "jarvis.aethers.my.id"),
    [string]$ConnectorServiceName = "Cloudflared",
    [string]$TunnelId = "",
    [int]$ConnectorMetricsPort = 20120,
    [int]$ProbeTimeoutSeconds = 8,
    [switch]$AllowNonElevated,
    [switch]$Apply,
    [switch]$Start
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Test observation hooks (env-gated; PRODUCTION never sets these).
#
# AETHER_TUNNEL_OBSERVER_JSON : path to a JSON file describing connector
#   observations as { scm: {name,processId,pathName,state} | null,
#                     processes: [ {processId,commandLine}, ... ] }.
#   When set, Get-ConnectorObservation reads it instead of CIM/WMI.
# AETHER_TUNNEL_START_CMD     : path to a .ps1 invoked in place of
#   Start-Service/Restart-Service. It may rewrite the observer JSON to
#   simulate post-start state and throw (non-zero exit) to simulate an SCM
#   start failure.
# AETHER_TUNNEL_READINESS     : "true"/"false" override for the connector
#   metrics readiness probe (default: real HTTP probe on the metrics port).
#
# Default (unset) behaviour always uses the real Windows observation path:
#   Win32_Service.ProcessId for the SCM PID and Win32_Process.CommandLine
#   for the exact connector command line.
# ---------------------------------------------------------------------------

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run this update from an elevated PowerShell session."
    }
}

if (-not (Test-Path -LiteralPath $TunnelConfig -PathType Leaf)) {
    throw "Tunnel config not found: $TunnelConfig"
}
if (-not $CloudflaredPath) {
    $CloudflaredPath = (Get-Command cloudflared.exe -ErrorAction Stop).Source
}

function Resolve-TunnelId {
    param([string]$ConfigPath)
    $raw = Get-Content -LiteralPath $ConfigPath -Raw -ErrorAction SilentlyContinue
    if ($raw) {
        $m = [regex]::Match($raw, '(?m)^\s*tunnel:\s*([0-9a-fA-F-]{36})\s*$')
        if ($m.Success) { return $m.Groups[1].Value }
    }
    return ""
}

if (-not $TunnelId) {
    $TunnelId = Resolve-TunnelId -ConfigPath $TunnelConfig
}

$original = Get-Content -LiteralPath $TunnelConfig -Raw
$lines = $original -split "`r?`n"

function Get-IngressEntries {
    param([string[]]$SourceLines)

    $entries = @()
    $inIngress = $false
    foreach ($line in $SourceLines) {
        if ($line.Trim() -eq "ingress:") { $inIngress = $true; continue }
        if (-not $inIngress) { continue }
        $m = [regex]::Match($line, '^\s*-\s+hostname:\s*(\S+)\s*$')
        if ($m.Success) {
            $entries += [ordered]@{ type = "hostname"; hostname = $m.Groups[1].Value; line = $line }
            continue
        }
        $m = [regex]::Match($line, '^\s*-\s+service:\s*(\S+)\s*$')
        if ($m.Success) {
            $entries += [ordered]@{ type = "service"; service = $m.Groups[1].Value; line = $line }
        }
    }
    return $entries
}

$entries = Get-IngressEntries -SourceLines $lines

$entryHosts = @($entries | Where-Object { $_.type -eq "hostname" } | ForEach-Object { $_.hostname })
$protectedMissing = @($ProtectedHostnames | Where-Object { $_ -notin $entryHosts })
if ($protectedMissing.Count -gt 0) {
    throw "Protected host(s) missing from shared tunnel config: $($protectedMissing -join ', ')"
}
$fallbackServices = @($entries | Where-Object { $_.type -eq "service" -and $_.service -eq "http_status:404" })
if ($fallbackServices.Count -ne 1) {
    throw "Expected exactly one http_status:404 fallback; found $($fallbackServices.Count)"
}

# --- Build candidate config: change ONLY the service scalar for Aether hosts. ---
$newLines = @()
$inIngress = $false
$replaced = 0
foreach ($line in $lines) {
    if ($line.Trim() -eq "ingress:") { $inIngress = $true; $newLines += $line; continue }
    if (-not $inIngress) { $newLines += $line; continue }

    $m = [regex]::Match($line, '^(\s*-\s+hostname:\s*)(\S+)(\s*)$')
    if ($m.Success -and ($AetherHostnames -contains $m.Groups[2].Value)) {
        $newLines += $line
        $replaced++
        continue
    }

    $svc = [regex]::Match($line, '^(\s*service:\s*)(\S+)(\s*)$')
    if ($svc.Success -and $replaced -gt 0) {
        $prevNonEmpty = $newLines | Where-Object { $_.Trim() -ne "" } | Select-Object -Last 1
        $prevHost = [regex]::Match($prevNonEmpty, '^\s*-\s+hostname:\s*(\S+)')
        if ($prevHost.Success -and ($AetherHostnames -contains $prevHost.Groups[1].Value)) {
            $newLines += $svc.Groups[1].Value + $LocalOrigin + $svc.Groups[3].Value
            $replaced--
            continue
        }
    }
    $newLines += $line
}

if ($replaced -ne 0) {
    throw "Aether hostname entry without a service scalar (unbalanced): remaining=$replaced"
}

$candidate = $newLines -join "`r`n"

function Assert-RoutePreservation {
    param([string]$Config)

    foreach ($protected in $ProtectedHostnames) {
        if ($Config -notmatch [regex]::Escape("hostname: $protected")) {
            throw "Protected host was lost: $protected"
        }
    }
    if (($Config -split "http_status:404").Count -ne 2) {
        throw "Fallback http_status:404 must appear exactly once"
    }
    foreach ($hostname in $AetherHostnames) {
        $count = ($Config -split [regex]::Escape("hostname: $hostname")).Count - 1
        if ($count -ne 1) {
            throw "Aether host '$hostname' must appear exactly once; found $count"
        }
    }
}

Assert-RoutePreservation -Config $candidate

$ingressDir = Join-Path $AetherHome "runtime\ingress"
New-Item -ItemType Directory -Force -Path $ingressDir | Out-Null
$receiptPath = Join-Path $ingressDir "shared-tunnel-receipt.json"

$receipt = [ordered]@{
    schema = "aether.shared-tunnel.v4"
    event = "cloudflare.shared_tunnel.updated"
    observed_at = (Get-Date).ToUniversalTime().ToString("o")
    applied = [bool]$Apply
    started = [bool]$Start
    aether_hostnames = $AetherHostnames
    aether_origin = $LocalOrigin
    protected_hostnames = $ProtectedHostnames
    connector_service = $ConnectorServiceName
    connector_metrics_port = $ConnectorMetricsPort
    tunnel_id = $TunnelId
    config_path = $TunnelConfig
    config_before_sha256 = (Get-FileHash -LiteralPath $TunnelConfig -Algorithm SHA256).Hash.ToLowerInvariant()
    candidate_sha256 = $null
    config_after_sha256 = $null
    validate_before_apply = $false
    live_config_replaced = $false
    rollback_triggered = $false
    recovery_proven = $null
    connector_mutation_started = $false
    connector_count_before = $null
    governed_pids_before = @()
    preserved_pids_before = @()
    connector_count_after = $null
    connector_service_pid = $null
    connector_pid = $null
    connector_cmdline = $null
    connector_bound = $false
    connector_readiness = $null
    error = $null
}

# ---- Connector observation via CIM/WMI (default) or env-gated test seam. ----
function Get-NormalizedPath {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return $Value }
    try { return ([IO.Path]::GetFullPath($Value)) }
    catch { return $Value }
}

function Get-ConnectorObservation {
    $hookJson = $env:AETHER_TUNNEL_OBSERVER_JSON
    if ($hookJson -and (Test-Path -LiteralPath $hookJson -PathType Leaf)) {
        $raw = Get-Content -LiteralPath $hookJson -Raw
        if ([string]::IsNullOrWhiteSpace($raw)) { return $null }
        return ($raw | ConvertFrom-Json)
    }
    $scm = $null
    $procs = @()
    try {
        $svc = Get-CimInstance Win32_Service -Filter "Name='$ConnectorServiceName'" -ErrorAction Stop
        if ($null -ne $svc) {
            $scm = [ordered]@{
                name = [string]$svc.Name
                processId = [int]$svc.ProcessId
                pathName = [string]$svc.PathName
                state = [string]$svc.State
            }
        }
    }
    catch {
        $scm = $null
    }
    try {
        foreach ($p in @(Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" -ErrorAction Stop)) {
            $procs += [ordered]@{
                processId = [int]$p.ProcessId
                commandLine = [string]$p.CommandLine
            }
        }
    }
    catch {
        $procs = @()
    }
    return [ordered]@{ scm = $scm; processes = $procs }
}

function Test-ProcessGoverned {
    param([string]$CommandLine)

    if ([string]::IsNullOrWhiteSpace($CommandLine)) { return $false }
    $cfgOk = $CommandLine -match [regex]::Escape((Get-NormalizedPath $TunnelConfig))
    $tunnelOk = $false
    if ($TunnelId) {
        $tunnelOk = $CommandLine -match [regex]::Escape($TunnelId)
    }
    $metricsOk = $CommandLine -match [regex]::Escape("127.0.0.1:$ConnectorMetricsPort")
    return (($cfgOk -or $tunnelOk) -and $metricsOk)
}

function Get-ScmConnectorInfo {
    # Exact SCM/tunnel/config binding from Win32_Service.ProcessId correlated
    # with Win32_Process.CommandLine. Returns $null when any observation is
    # missing so callers can fail closed instead of dereferencing garbage.
    $obs = Get-ConnectorObservation
    if ($null -eq $obs) { return $null }
    $scm = $obs.scm
    if ($null -eq $scm) { return $null }
    $scmPid = 0
    try { $scmPid = [int]$scm.processId } catch { return $null }
    if ($scmPid -le 0) { return $null }

    $matched = @($obs.processes | Where-Object {
        $null -ne $_ -and ([int]$_.processId -eq $scmPid)
    } | Select-Object -First 1)
    if ($matched.Count -ne 1) { return $null }

    $cmdline = [string]$matched[0].commandLine
    $cfgPath = Get-NormalizedPath $TunnelConfig
    $matchesConfig = $cmdline -match [regex]::Escape($cfgPath)
    # Exact config-derived tunnel binding: the connector process references our
    # config file, and that file carries the exact tunnel UUID we derived from
    # it. We never rely on the UUID appearing in the command line (production
    # cloudflared does not print it there).
    $matchesTunnel = $false
    if ($TunnelId) {
        $cfgRaw = Get-Content -LiteralPath $TunnelConfig -Raw -ErrorAction SilentlyContinue
        if ($cfgRaw) {
            $matchesTunnel = ($cfgRaw -match [regex]::Escape($TunnelId))
        }
    }
    $matchesMetrics = $cmdline -match [regex]::Escape("127.0.0.1:$ConnectorMetricsPort")

    return [ordered]@{
        pid = $scmPid
        service_pid = $scmPid
        cmdline = $cmdline
        matchesConfig = $matchesConfig
        matchesTunnel = $matchesTunnel
        matchesMetrics = $matchesMetrics
        isValid = ($matchesConfig -and $matchesTunnel -and $matchesMetrics)
    }
}

function Stop-GovernedCloudflaredProcesses {
    # Stops ONLY the SCM PID plus stale direct PIDs that positively match our
    # tunnel/config/metrics. Unrelated connectors (other tunnels) are preserved.
    $obs = Get-ConnectorObservation
    if ($null -eq $obs) { return @() }
    $scmPid = 0
    if ($null -ne $obs.scm) {
        try { $scmPid = [int]$obs.scm.processId } catch { $scmPid = 0 }
    }
    $governed = @()
    $preserved = @()
    foreach ($p in @($obs.processes | Where-Object { $null -ne $_ })) {
        $pidv = [int]$p.processId
        if ($pidv -eq $scmPid) {
            $governed += $pidv
            continue
        }
        if (Test-ProcessGoverned -CommandLine ([string]$p.commandLine)) {
            $governed += $pidv
        }
        else {
            $preserved += $pidv
        }
    }
    $receipt.governed_pids_before = @($governed)
    $receipt.preserved_pids_before = @($preserved)
    foreach ($pidv in $governed) {
        try { Stop-Process -Id $pidv -Force -ErrorAction Stop } catch { }
    }
    if ($governed.Count -gt 0) {
        Start-Sleep -Seconds 2
    }
    return @($governed)
}

function Restart-ScmConnector {
    # Governed handoff: stop only governed processes (SCM PID + positively
    # matched stale direct PIDs), then start the single SCM connector.
    $startHook = $env:AETHER_TUNNEL_START_CMD
    if ($startHook) {
        if (-not (Test-Path -LiteralPath $startHook -PathType Leaf)) {
            throw "AETHER_TUNNEL_START_CMD not found: $startHook"
        }
        Stop-GovernedCloudflaredProcesses | Out-Null
        & $startHook
        if ($LASTEXITCODE -ne 0) {
            throw "connector start hook failed (exit $LASTEXITCODE)"
        }
        Start-Sleep -Seconds 2
        return Get-ScmConnectorInfo
    }

    $svc = Get-Service -Name $ConnectorServiceName -ErrorAction SilentlyContinue
    if ($null -eq $svc) {
        throw "Connector SCM service '$ConnectorServiceName' missing."
    }
    Stop-GovernedCloudflaredProcesses | Out-Null
    if ($svc.Status -eq "Stopped") {
        Start-Service -Name $ConnectorServiceName -ErrorAction Stop | Out-Null
    }
    else {
        Restart-Service -Name $ConnectorServiceName -Force -ErrorAction Stop | Out-Null
    }
    Start-Sleep -Seconds 3
    return Get-ScmConnectorInfo
}

function Assert-SingleConnector {
    $info = Get-ScmConnectorInfo
    if ($null -eq $info) {
        throw "SCM connector binding could not be observed (service or process missing)."
    }
    $obs = Get-ConnectorObservation
    $governed = @()
    if ($null -ne $obs) {
        $governed = @($obs.processes | Where-Object {
            $null -ne $_ -and (Test-ProcessGoverned -CommandLine ([string]$_.commandLine))
        })
    }
    $receipt.connector_count_after = $governed.Count
    if ($governed.Count -ne 1) {
        throw "Expected exactly one governed connector process; found $($governed.Count)"
    }
    if (-not $info.isValid) {
        throw "SCM connector does not match expected config/tunnel/metrics. service_pid=$($info.service_pid), cmdline=$($info.cmdline)"
    }
    $receipt.connector_count_after = 1
    $receipt.connector_pid = $info.pid
    $receipt.connector_service_pid = $info.service_pid
    $receipt.connector_cmdline = $info.cmdline
    $receipt.connector_bound = $true
    return $true
}

function Test-ConnectorReadiness {
    $readinessEnv = $env:AETHER_TUNNEL_READINESS
    if ($null -ne $readinessEnv) {
        return ($readinessEnv -match '(?i)^true')
    }
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$ConnectorMetricsPort/metrics" -TimeoutSec $ProbeTimeoutSeconds -UseBasicParsing
        return ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 300)
    }
    catch {
        return $false
    }
}

if (-not $Apply) {
    $receipt.candidate_sha256 = (
        [System.BitConverter]::ToString(
            [System.Security.Cryptography.SHA256]::Create().ComputeHash(
                [Text.Encoding]::UTF8.GetBytes($candidate)
            )
        ).Replace("-", "").ToLowerInvariant()
    )
    $receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receiptPath -Encoding UTF8
    $receipt | ConvertTo-Json -Depth 8
    return
}

# ---- Elevation gate BEFORE any mutation. ----
if (-not $AllowNonElevated) {
    Assert-Administrator
}

# ---- Validate-before-apply + atomic replace. ----
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$candidatePath = "$TunnelConfig.candidate-$stamp"
$backupPath = "$TunnelConfig.bak-$stamp"
Set-Content -LiteralPath $candidatePath -Value $candidate -Encoding UTF8
$receipt.candidate_sha256 = (Get-FileHash -LiteralPath $candidatePath -Algorithm SHA256).Hash.ToLowerInvariant()

function Restore-SharedTunnelState {
    # Restore the live config to its backup and reconcile the connector back to
    # a single governed SCM process. Never claims recovery unless observed.
    if (Test-Path -LiteralPath $backupPath) {
        Copy-Item -LiteralPath $backupPath -Destination $TunnelConfig -Force
    }
    $receipt.config_after_sha256 = (Get-FileHash -LiteralPath $TunnelConfig -Algorithm SHA256).Hash.ToLowerInvariant()

    $recovered = $false
    if ($receipt.connector_mutation_started) {
        try {
            Stop-GovernedCloudflaredProcesses | Out-Null
            $startHook = $env:AETHER_TUNNEL_START_CMD
            if ($startHook -and (Test-Path -LiteralPath $startHook -PathType Leaf)) {
                & $startHook | Out-Null
            }
            else {
                $svc = Get-Service -Name $ConnectorServiceName -ErrorAction SilentlyContinue
                if ($null -ne $svc) {
                    if ($svc.Status -eq "Stopped") {
                        Start-Service -Name $ConnectorServiceName -ErrorAction Stop | Out-Null | Out-Null
                    }
                    else {
                        Restart-Service -Name $ConnectorServiceName -Force -ErrorAction Stop | Out-Null | Out-Null
                    }
                }
            }
            Start-Sleep -Seconds 2
            $info = Get-ScmConnectorInfo
            if ($null -ne $info -and $info.isValid) {
                $recovered = (Test-ConnectorReadiness)
            }
        }
        catch {
            $recovered = $false
        }
    }
    else {
        $recovered = $true  # no connector mutation was performed -> config restore is sufficient
    }
    $receipt.recovery_proven = $recovered
    return $recovered
}

try {
    & $CloudflaredPath tunnel --config $candidatePath ingress validate 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "cloudflared ingress validate failed on candidate (exit $LASTEXITCODE)"
    }
    $receipt.validate_before_apply = $true

    Copy-Item -LiteralPath $TunnelConfig -Destination $backupPath -Force
    Move-Item -LiteralPath $candidatePath -Destination $TunnelConfig -Force
    $receipt.live_config_replaced = $true

    Assert-RoutePreservation -Config (Get-Content -LiteralPath $TunnelConfig -Raw)
    $receipt.config_after_sha256 = (Get-FileHash -LiteralPath $TunnelConfig -Algorithm SHA256).Hash.ToLowerInvariant()

    if ($Start) {
        $obs = Get-ConnectorObservation
        $governedBefore = @()
        if ($null -ne $obs) {
            $governedBefore = @($obs.processes | Where-Object {
                $null -ne $_ -and (Test-ProcessGoverned -CommandLine ([string]$_.commandLine))
            })
        }
        $receipt.connector_count_before = $governedBefore.Count
        $receipt.connector_mutation_started = $true

        $connectorService = Restart-ScmConnector
        Assert-SingleConnector | Out-Null
        $metricsOk = Test-ConnectorReadiness
        $receipt.connector_readiness = $metricsOk
        if (-not $metricsOk) {
            throw "cloudflared connector readiness (metrics) failed after apply."
        }
    }
}
catch {
    $receipt.rollback_triggered = $true
    $receipt.error = $_.Exception.Message
    if ($receipt.live_config_replaced) {
        $receipt.recovery_proven = (Restore-SharedTunnelState)
    }
    if (Test-Path -LiteralPath $candidatePath) {
        Remove-Item -LiteralPath $candidatePath -Force -ErrorAction SilentlyContinue
    }
    $receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receiptPath -Encoding UTF8
    throw
}

if (Test-Path -LiteralPath $candidatePath) {
    Remove-Item -LiteralPath $candidatePath -Force
}
$receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receiptPath -Encoding UTF8
$receipt | ConvertTo-Json -Depth 8
