[CmdletBinding()]
param(
    [string]$Output = (Join-Path $PSScriptRoot 'windows-readiness.json')
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Find-Command([string]$Name) {
    $item = Get-Command $Name -ErrorAction SilentlyContinue
    if ($item) { return $item.Source }
    return $null
}

function Invoke-PythonProbe([string]$Executable, [string[]]$PrefixArguments = @()) {
    try {
        $arguments = @($PrefixArguments) + @('-c', 'import sys; print(sys.version.split()[0])')
        $output = & $Executable @arguments 2>$null
        if ($LASTEXITCODE -eq 0 -and $output) {
            return ($output | Select-Object -First 1).ToString().Trim()
        }
    } catch {
        return $null
    }
    return $null
}

function Get-PortableRuntimeArchitecture {
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

$os = Get-CimInstance Win32_OperatingSystem
$cpu = Get-CimInstance Win32_ComputerSystem
$systemDrive = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$($env:SystemDrive)'"
$commands = [ordered]@{}
foreach ($name in @('py','python','git','bun','node','caddy','cloudflared','AionUi','codex','claude','gemini','opencode')) {
    $commands[$name] = Find-Command $name
}

$pythonVersion = $null
$pythonReady = $false
if ($commands['py']) {
    $pythonVersion = Invoke-PythonProbe -Executable $commands['py'] -PrefixArguments @('-3.11')
}
if (-not $pythonVersion -and $commands['python']) {
    $pythonVersion = Invoke-PythonProbe -Executable $commands['python']
}
if ($pythonVersion) {
    $parts = $pythonVersion.Split('.')
    $pythonReady = ([int]$parts[0] -gt 3) -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 11)
}

$runtimeArchitecture = Get-PortableRuntimeArchitecture
$reportedArchitecture = $runtimeArchitecture
if ($os -and ($os.PSObject.Properties.Name -contains 'OSArchitecture')) {
    $candidateArchitecture = [string]$os.OSArchitecture
    if (-not [string]::IsNullOrWhiteSpace($candidateArchitecture)) {
        $reportedArchitecture = $candidateArchitecture
    }
}

$report = [ordered]@{
    generated_at = [DateTimeOffset]::UtcNow.ToString('o')
    operating_system = [ordered]@{
        caption = $os.Caption
        version = $os.Version
        build = $os.BuildNumber
        architecture = $reportedArchitecture
        runtime_architecture = $runtimeArchitecture
        supported_family = $os.Caption -match 'Windows'
    }
    capacity = [ordered]@{
        logical_processors = [int]$cpu.NumberOfLogicalProcessors
        memory_gb = [math]::Round($cpu.TotalPhysicalMemory / 1GB, 2)
        system_drive_free_gb = [math]::Round($systemDrive.FreeSpace / 1GB, 2)
        system_drive_size_gb = [math]::Round($systemDrive.Size / 1GB, 2)
    }
    python = [ordered]@{
        version = $pythonVersion
        supported = $pythonReady
        launcher_found = [bool]$commands['py']
        interpreter_found = [bool]$pythonVersion
        remediation = if ($pythonReady) { $null } else { 'Install 64-bit Python 3.11 or newer, enable the Python launcher/PATH, reopen PowerShell, then rerun readiness.' }
    }
    commands = $commands
    assessment = [ordered]@{
        core_gateway_candidate = $pythonReady
        recommended_for_alpha = ($pythonReady -and ($cpu.TotalPhysicalMemory -ge 4GB) -and ($systemDrive.FreeSpace -ge 10GB))
        production_adapter_complete = $false
        missing_production_layers = @(
            'Windows Service supervision for Gateway and optional LiveKit worker',
            'AionUi WebUI installation and persistence',
            'Caddy Windows service and internal route configuration',
            'cloudflared Windows service and tunnel route',
            'Windows CI evidence for first pulse, live provider, LiveKit, and runtime body',
            'Platform-aware shell/tool policy'
        )
    }
}
$json = $report | ConvertTo-Json -Depth 10
[System.IO.File]::WriteAllText($Output, $json + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
$json
