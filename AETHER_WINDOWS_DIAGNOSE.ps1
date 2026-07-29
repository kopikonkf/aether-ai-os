[CmdletBinding()]
param(
    [ValidateSet('All','Gateway','Telegram','Browser')]
    [string]$Area = 'All',
    [string]$ReleaseRoot = $PSScriptRoot,
    [int]$Port = 8000,
    [switch]$CopyOperatorToken,
    [switch]$OpenSenses,
    [switch]$DeleteTelegramWebhook,
    [long]$TelegramProbeChatId = 0
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Write-Section([string]$Title) {
    Write-Host "`n=== $Title ===" -ForegroundColor Cyan
}

function Read-DotEnv([string]$Path) {
    $map = @{}
    if (-not (Test-Path -LiteralPath $Path)) { return $map }
    foreach ($raw in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $line = $raw.Trim()
        if (-not $line -or $line.StartsWith('#')) { continue }
        $index = $line.IndexOf('=')
        if ($index -lt 1) { continue }
        $key = $line.Substring(0, $index).Trim()
        $value = $line.Substring($index + 1).Trim()
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            if ($value.Length -ge 2) { $value = $value.Substring(1, $value.Length - 2) }
        }
        $map[$key] = $value
    }
    return $map
}


function Get-EnvValue([hashtable]$Map, [string]$Key) {
    if ($Map.ContainsKey($Key) -and $null -ne $Map[$Key]) { return [string]$Map[$Key] }
    return ''
}

function Get-GatewayProcess([string]$PidFile) {
    if (-not (Test-Path -LiteralPath $PidFile)) { return $null }
    $raw = (Get-Content -LiteralPath $PidFile -Raw).Trim()
    $pidValue = 0
    if (-not [int]::TryParse($raw, [ref]$pidValue)) { return $null }
    try { return Get-Process -Id $pidValue -ErrorAction Stop } catch { return $null }
}

function Show-LogTail([string]$Path, [int]$Lines = 60) {
    if (Test-Path -LiteralPath $Path) {
        Write-Host "--- $Path (last $Lines lines) ---" -ForegroundColor DarkGray
        Get-Content -LiteralPath $Path -Tail $Lines
    } else {
        Write-Host "Missing log: $Path" -ForegroundColor Yellow
    }
}

$Root = (Resolve-Path -LiteralPath $ReleaseRoot).Path
$EnvPath = Join-Path $Root 'aether-core\.env'
$RuntimeDir = Join-Path $Root '.aether-windows'
$PidFile = Join-Path $RuntimeDir 'gateway.pid'
$StdoutLog = Join-Path $RuntimeDir 'logs\gateway.stdout.log'
$StderrLog = Join-Path $RuntimeDir 'logs\gateway.stderr.log'
$Values = Read-DotEnv $EnvPath
$Gateway = Get-GatewayProcess $PidFile

if ($Area -in @('All','Gateway')) {
    Write-Section 'Gateway'
    if ($Gateway) {
        Write-Host "Process: RUNNING (PID $($Gateway.Id), started $($Gateway.StartTime.ToString('o')))" -ForegroundColor Green
        if (Test-Path -LiteralPath $EnvPath) {
            $envWrite = (Get-Item -LiteralPath $EnvPath).LastWriteTime
            $stale = $envWrite -gt $Gateway.StartTime
            Write-Host "Environment file last changed: $($envWrite.ToString('o'))"
            Write-Host "Restart required for current .env: $stale" -ForegroundColor $(if ($stale) { 'Yellow' } else { 'Green' })
        }
    } else {
        Write-Host 'Process: NOT RUNNING' -ForegroundColor Red
    }
    try {
        $status = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/status" -TimeoutSec 5
        Write-Host "HTTP health: ONLINE; cognition=$($status.cognition); model_provider=$($status.model_provider)" -ForegroundColor Green
    } catch {
        Write-Host "HTTP health: FAILED - $($_.Exception.Message)" -ForegroundColor Red
    }
    Show-LogTail $StderrLog 80
}

if ($Area -in @('All','Telegram')) {
    Write-Section 'Telegram'
    $enabled = ((Get-EnvValue $Values 'TELEGRAM_ENABLED').Trim().ToLowerInvariant() -eq 'true')
    $token = (Get-EnvValue $Values 'TELEGRAM_BOT_TOKEN').Trim()
    $allowedRaw = (Get-EnvValue $Values 'TELEGRAM_ALLOWED_USER_IDS').Trim()
    $allowed = @($allowedRaw -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    $invalidAllowed = @($allowed | Where-Object { $_ -notmatch '^\d+$' })

    Write-Host "Enabled: $enabled"
    Write-Host "Bot token configured: $([bool]$token)"
    Write-Host "Allowed user IDs: $($allowed.Count) numeric value(s)"
    if ($invalidAllowed.Count -gt 0) {
        Write-Host "Invalid allowlist values: $($invalidAllowed -join ', ')" -ForegroundColor Red
        Write-Host 'Use numeric Telegram user IDs only; do not use @username or a group chat ID.' -ForegroundColor Yellow
    }
    if (-not $enabled) { Write-Host 'Set TELEGRAM_ENABLED=true, then restart Gateway.' -ForegroundColor Yellow }
    if (-not $token) { Write-Host 'Set TELEGRAM_BOT_TOKEN, then restart Gateway.' -ForegroundColor Yellow }

    if ($token) {
        $base = "https://api.telegram.org/bot$token"
        try {
            $me = Invoke-RestMethod -Uri "$base/getMe" -Method Get -TimeoutSec 15
            if ($me.ok) {
                Write-Host "Bot API: OK; id=$($me.result.id); username=@$($me.result.username)" -ForegroundColor Green
            } else {
                Write-Host 'Bot API getMe returned ok=false.' -ForegroundColor Red
            }
        } catch {
            Write-Host "Bot API getMe failed: $($_.Exception.Message)" -ForegroundColor Red
        }

        try {
            $hook = Invoke-RestMethod -Uri "$base/getWebhookInfo" -Method Get -TimeoutSec 15
            $hasWebhook = [bool]($hook.result.url)
            Write-Host "Webhook configured: $hasWebhook"
            Write-Host "Pending updates: $($hook.result.pending_update_count)"
            if ($hook.result.last_error_message) {
                Write-Host "Last webhook error: $($hook.result.last_error_message)" -ForegroundColor Yellow
            }
            if ($hasWebhook) {
                Write-Host 'Aether v0.19.2 uses long polling; an existing webhook blocks polling.' -ForegroundColor Red
                if ($DeleteTelegramWebhook) {
                    $deleted = Invoke-RestMethod -Uri "$base/deleteWebhook" -Method Post -Body @{ drop_pending_updates = 'false' } -TimeoutSec 15
                    Write-Host "Webhook deletion result: $($deleted.ok)" -ForegroundColor $(if ($deleted.ok) { 'Green' } else { 'Red' })
                } else {
                    Write-Host 'Rerun with -DeleteTelegramWebhook to remove it explicitly.' -ForegroundColor Yellow
                }
            }
        } catch {
            Write-Host "Bot API getWebhookInfo failed: $($_.Exception.Message)" -ForegroundColor Red
        }

        if ($TelegramProbeChatId -ne 0) {
            try {
                $probe = Invoke-RestMethod -Uri "$base/sendMessage" -Method Post -Body @{
                    chat_id = "$TelegramProbeChatId"
                    text = 'Aether Telegram outbound transport probe.'
                } -TimeoutSec 15
                Write-Host "Outbound probe sent: $($probe.ok)" -ForegroundColor $(if ($probe.ok) { 'Green' } else { 'Red' })
            } catch {
                Write-Host "Outbound probe failed: $($_.Exception.Message)" -ForegroundColor Red
            }
        }
    }

    if ($Gateway -and (Test-Path -LiteralPath $EnvPath)) {
        $stale = (Get-Item -LiteralPath $EnvPath).LastWriteTime -gt $Gateway.StartTime
        if ($stale) {
            Write-Host 'CRITICAL: Gateway started before the latest .env edit. Run -Action Restart.' -ForegroundColor Yellow
        }
    }
    Show-LogTail $StderrLog 100
}

if ($Area -in @('All','Browser')) {
    Write-Section 'Browser Senses'
    $operatorToken = (Get-EnvValue $Values 'AETHER_OPERATOR_TOKEN').Trim()
    Write-Host "Operator token configured: $([bool]$operatorToken)"
    Write-Host "Senses URL: http://127.0.0.1:$Port/senses"
    try {
        $senses = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/browser-senses/status" -TimeoutSec 5
        Write-Host "Browser Senses API: ONLINE; sessions=$($senses.store.sessions); livekit_ready=$($senses.livekit.ready)" -ForegroundColor Green
    } catch {
        Write-Host "Browser Senses API failed: $($_.Exception.Message)" -ForegroundColor Red
    }
    if ($CopyOperatorToken) {
        if (-not $operatorToken) { throw 'AETHER_OPERATOR_TOKEN is not configured.' }
        Set-Clipboard -Value $operatorToken
        Write-Host 'Operator token copied to clipboard. Paste it into Connection and privacy > Founder/operator token.' -ForegroundColor Green
    }
    if ($OpenSenses) {
        Start-Process "http://127.0.0.1:$Port/senses"
    }
    Write-Host 'OFFLINE / Transport not initialized is the expected pre-session UI state.' -ForegroundColor DarkGray
    Write-Host 'Connect Sense must issue a browser session before text, microphone, or camera turns are accepted.' -ForegroundColor DarkGray
}
