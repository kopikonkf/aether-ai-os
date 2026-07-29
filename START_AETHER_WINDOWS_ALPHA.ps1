[CmdletBinding()]
param(
    [ValidateSet('Init','Doctor','Smoke','Pulse','Start','Restart','Status','Stop','All')]
    [string]$Action = 'All',
    [string]$ReleaseRoot = $PSScriptRoot,
    [string]$DataRoot = '',
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Write-Step([string]$Message) {
    Write-Host "[Aether Windows] $Message" -ForegroundColor Cyan
}

function Get-ReleaseBuildId([string]$Root) {
    $manifest = Join-Path $Root 'RELEASE_BUILD.json'
    if (-not (Test-Path -LiteralPath $manifest)) { return 'v0.19.2-base' }
    try {
        return [string]((Get-Content -LiteralPath $manifest -Raw -Encoding UTF8 | ConvertFrom-Json).build_id)
    } catch {
        throw "Invalid release build manifest: $manifest"
    }
}

function Get-PortableOSDescription {
    try {
        $runtimeType = [System.Runtime.InteropServices.RuntimeInformation]
        $property = $runtimeType.GetProperty('OSDescription')
        if ($null -ne $property) {
            $value = [string]$property.GetValue($null, $null)
            if (-not [string]::IsNullOrWhiteSpace($value)) { return $value }
        }
    } catch {}

    try {
        $os = Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop
        $parts = @()
        if ($os.PSObject.Properties.Name -contains 'Caption') { $parts += [string]$os.Caption }
        if ($os.PSObject.Properties.Name -contains 'Version') { $parts += "version $($os.Version)" }
        $value = ($parts | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) -join ' '
        if (-not [string]::IsNullOrWhiteSpace($value)) { return $value }
    } catch {}

    return [Environment]::OSVersion.VersionString
}

function Get-PortableOSArchitecture {
    try {
        $runtimeType = [System.Runtime.InteropServices.RuntimeInformation]
        $property = $runtimeType.GetProperty('OSArchitecture')
        if ($null -ne $property) {
            $value = $property.GetValue($null, $null)
            if ($null -ne $value) { return [string]$value }
        }
    } catch {}

    if ([Environment]::Is64BitOperatingSystem) { return 'X64' }
    $candidate = [string]$env:PROCESSOR_ARCHITECTURE
    if (-not [string]::IsNullOrWhiteSpace($candidate)) { return $candidate }
    return 'Unknown'
}

function Test-PythonCandidate([string]$Executable, [string[]]$PrefixArguments = @()) {
    try {
        $arguments = @($PrefixArguments) + @('-c', 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)')
        & $Executable @arguments 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Resolve-PythonLauncher {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py -and (Test-PythonCandidate -Executable $py.Source -PrefixArguments @('-3.11'))) {
        return @($py.Source, '-3.11')
    }

    foreach ($name in @('python','python3')) {
        $candidate = Get-Command $name -ErrorAction SilentlyContinue
        if ($candidate -and (Test-PythonCandidate -Executable $candidate.Source)) {
            return @($candidate.Source)
        }
    }

    $launcherNote = if ($py) {
        'The py.exe launcher exists, but it has no usable Python 3.11 runtime.'
    } else {
        'No Python launcher or interpreter was found.'
    }
    throw "$launcherNote Install 64-bit Python 3.11 or newer, enable the Python launcher/PATH, close and reopen PowerShell, then rerun this command."
}

function Set-DotEnvValue([string]$Path, [string]$Key, [string]$Value) {
    $lines = @()
    if (Test-Path $Path) {
        $lines = @(Get-Content -LiteralPath $Path -Encoding UTF8)
    }
    $prefix = "$Key="
    $found = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i].StartsWith($prefix, [System.StringComparison]::Ordinal)) {
            $lines[$i] = "$prefix$Value"
            $found = $true
            break
        }
    }
    if (-not $found) {
        $lines += "$prefix$Value"
    }
    [System.IO.File]::WriteAllLines($Path, $lines, [System.Text.UTF8Encoding]::new($false))
}

$Root = (Resolve-Path -LiteralPath $ReleaseRoot).Path
$Bringup = Join-Path $Root 'scripts\founder_bringup.py'
$CoreEnv = Join-Path $Root 'aether-core\.env'
$Venv = Join-Path $Root '.venv'
$VenvPython = Join-Path $Venv 'Scripts\python.exe'
$RuntimeDir = Join-Path $Root '.aether-windows'
$LogDir = Join-Path $RuntimeDir 'logs'
$PidFile = Join-Path $RuntimeDir 'gateway.pid'
$EvidenceFile = Join-Path $RuntimeDir 'windows-alpha-evidence.json'
$InstallMarker = Join-Path $RuntimeDir 'installed-build.txt'
$ReleaseBuildId = Get-ReleaseBuildId $Root

if (-not (Test-Path $Bringup)) {
    throw "Release root is invalid: missing $Bringup"
}
New-Item -ItemType Directory -Force -Path $RuntimeDir, $LogDir | Out-Null

if ([string]::IsNullOrWhiteSpace($DataRoot)) {
    if ($env:LOCALAPPDATA) {
        $DataRoot = Join-Path $env:LOCALAPPDATA 'Aether'
    } else {
        $DataRoot = Join-Path $env:USERPROFILE '.aether'
    }
}

function Ensure-Venv {
    $venvExisted = Test-Path $VenvPython
    if (-not $venvExisted) {
        $launcher = Resolve-PythonLauncher
        Write-Step "Creating virtual environment at $Venv"
        if ($launcher.Count -eq 2) {
            & $launcher[0] $launcher[1] -m venv $Venv
        } else {
            & $launcher[0] -m venv $Venv
        }
        if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
    }

    $installedBuild = if (Test-Path -LiteralPath $InstallMarker) {
        (Get-Content -LiteralPath $InstallMarker -Raw).Trim()
    } else { '' }
    $needsInstall = (-not $venvExisted) -or ($installedBuild -ne $ReleaseBuildId)
    if (-not $needsInstall) {
        Write-Step "Pinned Aether wheels already installed for build $ReleaseBuildId"
        return
    }

    Write-Step "Installing pinned Aether release wheels for build $ReleaseBuildId"
    & $VenvPython -m pip install --disable-pip-version-check --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw 'pip upgrade failed.' }

    $wheels = @(
        (Join-Path $Root 'dist\aether_core-0.19.2-py3-none-any.whl'),
        (Join-Path $Root 'dist\aether_tools-0.3.0-py3-none-any.whl'),
        (Join-Path $Root 'dist\aether_gateway-0.19.2-py3-none-any.whl')
    )
    foreach ($wheel in $wheels) {
        if (-not (Test-Path -LiteralPath $wheel)) { throw "Missing release wheel: $wheel" }
    }

    # First pass installs or repairs dependencies. The second pass is required
    # when a consolidated build retains the same semantic package version but
    # ships corrected wheel contents.
    & $VenvPython -m pip install @wheels
    if ($LASTEXITCODE -ne 0) { throw 'Aether dependency installation failed.' }
    & $VenvPython -m pip install --force-reinstall --no-deps @wheels
    if ($LASTEXITCODE -ne 0) { throw 'Aether consolidated wheel installation failed.' }
    Set-Content -LiteralPath $InstallMarker -Value $ReleaseBuildId -Encoding ASCII
}

$script:LastBringupExitCode = 0

function Invoke-Bringup([string[]]$Arguments) {
    $oldPath = $env:PYTHONPATH
    $exitCode = 1
    try {
        $env:PYTHONPATH = @(
            (Join-Path $Root 'aether-core\src'),
            (Join-Path $Root 'aether-tools\src'),
            (Join-Path $Root 'aether-gateway\src')
        ) -join [System.IO.Path]::PathSeparator
        & $VenvPython $Bringup @Arguments
        $exitCode = [int]$LASTEXITCODE
    } finally {
        $env:PYTHONPATH = $oldPath
        $script:LastBringupExitCode = $exitCode
    }
}

function Initialize-Aether {
    Ensure-Venv
    if (-not (Test-Path $CoreEnv)) {
        Write-Step 'Creating Aether environment and local secrets'
        Invoke-Bringup @('init','--port',"$Port")
        $code = $script:LastBringupExitCode
        if ($code -ne 0) { throw "Aether init failed with exit code $code" }
    } else {
        Write-Step 'Preserving existing aether-core\.env'
    }
    New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null
    Set-DotEnvValue -Path $CoreEnv -Key 'AETHER_HOME' -Value $DataRoot
    Set-DotEnvValue -Path $CoreEnv -Key 'HOST' -Value '127.0.0.1'
    Set-DotEnvValue -Path $CoreEnv -Key 'PORT' -Value "$Port"
}

function Invoke-Doctor {
    Ensure-Venv
    Invoke-Bringup @('doctor')
    $code = $script:LastBringupExitCode
    if ($code -ne 0) { throw "Aether doctor failed with exit code $code" }
}

function Invoke-Smoke {
    Ensure-Venv
    Invoke-Bringup @('smoke')
    $code = $script:LastBringupExitCode
    if ($code -ne 0) { throw "Aether first pulse failed with exit code $code" }
}

function Get-GatewayProcess {
    if (-not (Test-Path $PidFile)) { return $null }
    $raw = (Get-Content -LiteralPath $PidFile -Raw).Trim()
    $pidValue = 0
    if (-not [int]::TryParse($raw, [ref]$pidValue)) { return $null }
    try { return Get-Process -Id $pidValue -ErrorAction Stop } catch { return $null }
}

function Start-Gateway {
    Ensure-Venv
    if (-not (Test-Path $CoreEnv)) { Initialize-Aether }
    $existing = Get-GatewayProcess
    if ($existing) {
        Write-Step "Gateway is already running as PID $($existing.Id)"
        return
    }

    $pythonPath = @(
        (Join-Path $Root 'aether-core\src'),
        (Join-Path $Root 'aether-tools\src'),
        (Join-Path $Root 'aether-gateway\src')
    ) -join [System.IO.Path]::PathSeparator
    $oldPath = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = $pythonPath
        $stdout = Join-Path $LogDir 'gateway.stdout.log'
        $stderr = Join-Path $LogDir 'gateway.stderr.log'
        Write-Step "Starting Gateway on http://127.0.0.1:$Port"
        $process = Start-Process `
            -FilePath $VenvPython `
            -ArgumentList @('-m','aether_gateway.api.server') `
            -WorkingDirectory $Root `
            -RedirectStandardOutput $stdout `
            -RedirectStandardError $stderr `
            -PassThru `
            -WindowStyle Hidden
        Set-Content -LiteralPath $PidFile -Value $process.Id -Encoding ASCII
    } finally {
        $env:PYTHONPATH = $oldPath
    }

    $deadline = [DateTimeOffset]::UtcNow.AddSeconds(30)
    do {
        Start-Sleep -Milliseconds 500
        try {
            $status = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/status" -TimeoutSec 3
            Write-Step "Gateway healthy; PID $($process.Id)"
            return
        } catch {
            if ($process.HasExited) {
                throw "Gateway exited with code $($process.ExitCode). Inspect $stderr"
            }
        }
    } while ([DateTimeOffset]::UtcNow -lt $deadline)
    throw "Gateway did not become healthy within 30 seconds. Inspect $stderr"
}

function Stop-Gateway {
    $process = Get-GatewayProcess
    if (-not $process) {
        Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
        Write-Step 'Gateway is not running'
        return
    }
    Write-Step "Stopping Gateway PID $($process.Id)"
    Stop-Process -Id $process.Id -ErrorAction Stop
    try { Wait-Process -Id $process.Id -Timeout 10 -ErrorAction Stop } catch {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
}

function Show-Status {
    $process = Get-GatewayProcess
    $online = $false
    $body = $null
    try {
        $body = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/status" -TimeoutSec 3
        $online = $true
    } catch {}
    $evidence = [ordered]@{
        release = '0.19.2'
        build_id = $ReleaseBuildId
        generated_at = [DateTimeOffset]::UtcNow.ToString('o')
        os = Get-PortableOSDescription
        architecture = Get-PortableOSArchitecture
        release_root = $Root
        data_root = $DataRoot
        python = if (Test-Path $VenvPython) { (& $VenvPython -c 'import sys; print(sys.version.split()[0])') } else { $null }
        gateway = [ordered]@{
            online = $online
            url = "http://127.0.0.1:$Port"
            pid = if ($process) { $process.Id } else { $null }
            status = $body
        }
        logs = $LogDir
        known_boundary = 'Founder alpha launcher only; Windows Services, AionUi, Caddy, cloudflared, and LiveKit service installation are separate deployment-adapter work.'
    }
    $json = $evidence | ConvertTo-Json -Depth 12
    [System.IO.File]::WriteAllText($EvidenceFile, $json + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
    $json
}

switch ($Action) {
    'Init'   { Initialize-Aether }
    'Doctor' { Invoke-Doctor }
    'Smoke'  { Invoke-Smoke }
    'Pulse'  {
        Initialize-Aether
        Invoke-Doctor
        Invoke-Smoke
    }
    'Start'  { Start-Gateway; Show-Status }
    'Restart' { Stop-Gateway; Start-Gateway; Show-Status }
    'Status' { Show-Status }
    'Stop'   { Stop-Gateway; Show-Status }
    'All'    {
        Initialize-Aether
        Invoke-Doctor
        Invoke-Smoke
        Start-Gateway
        Show-Status
    }
}
