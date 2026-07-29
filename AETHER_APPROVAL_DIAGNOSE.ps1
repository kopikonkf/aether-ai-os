[CmdletBinding()]
param(
    [string]$ApprovalId = '',
    [string]$ReleaseRoot = $PSScriptRoot,
    [int]$Limit = 10
)
$ErrorActionPreference = 'Stop'
$python = Join-Path $ReleaseRoot '.venv\Scripts\python.exe'
$script = Join-Path $ReleaseRoot 'scripts\aether_approval_diagnose.py'
if (-not (Test-Path -LiteralPath $python)) { throw "Aether virtual environment not found: $python" }
$argsList = @($script, '--release-root', $ReleaseRoot, '--limit', "$Limit")
if ($ApprovalId) { $argsList += @('--approval-id', $ApprovalId) }
& $python @argsList
exit $LASTEXITCODE
