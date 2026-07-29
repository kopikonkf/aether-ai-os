# MCP Founder Local Proof — Windows

## Purpose

Prove that the merged read-only Aether Operational MCP server can be used by a local Codex client without mutating the Git repository or `AETHER_HOME`.

Use a local client because the baseline is a local MCP `stdio` server:

- ChatGPT desktop app in Codex mode — recommended on Windows;
- Codex CLI;
- Codex IDE extension.

ChatGPT web does not read local Codex MCP configuration.

## Canonical local paths

```text
Repository:
C:\Github\aether-ai-os

Laptop AETHER_HOME:
C:\Users\hp\AppData\Local\Aether
```

Keep `AETHER_HOME` outside the repository. Never copy `.env`, credentials, SQLite state, logs, frames, or backups into Git.

## 1. Clone and install current `main`

```powershell
New-Item -ItemType Directory -Force C:\Github | Out-Null
Set-Location C:\Github

git clone https://github.com/kopikonkf/aether-ai-os.git
Set-Location C:\Github\aether-ai-os

git status --short
git log -1 --oneline

py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install `
    -e .\aether-core `
    -e .\aether-tools `
    -e ".\aether-gateway[dev]"

.\.venv\Scripts\aether-mcp.exe --help
```

Expected:

- `git status --short` prints nothing;
- `aether-mcp.exe` exists under `.venv\Scripts`;
- the accepted frozen.2 runtime remains untouched because this is a separate development checkout.

## 2. Quiesce the laptop runtime

Close the launcher or PowerShell process running Gateway/Telegram. Verify no Gateway listener remains:

```powershell
Get-NetTCPConnection `
    -LocalPort 8000 `
    -State Listen `
    -ErrorAction SilentlyContinue
```

Expected: no output.

## 3. Capture the pre-proof state manifest

```powershell
$RepoRoot = "C:\Github\aether-ai-os"
$AetherHome = "$env:LOCALAPPDATA\Aether"
$ProofRoot = Join-Path $RepoRoot ".proof\mcp-founder"
$BeforePath = Join-Path $ProofRoot "aether-home-before.json"

New-Item -ItemType Directory -Force $ProofRoot | Out-Null

function Get-AetherManifest([string]$Root) {
    @(
        Get-ChildItem -LiteralPath $Root -Recurse -Force -File |
            Sort-Object FullName |
            ForEach-Object {
                [pscustomobject]@{
                    path = [IO.Path]::GetRelativePath(
                        $Root, $_.FullName
                    ).Replace("\", "/")
                    size_bytes = $_.Length
                    sha256 = (
                        Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256
                    ).Hash.ToLowerInvariant()
                }
            }
    )
}

$Before = Get-AetherManifest $AetherHome
$Before | ConvertTo-Json -Depth 4 |
    Set-Content -LiteralPath $BeforePath -Encoding UTF8

Write-Host "Captured $($Before.Count) AETHER_HOME files."
```

`.proof/` is ignored by Git and is outside `AETHER_HOME`.

## 4. Register `aether-mcp`

### Recommended: ChatGPT desktop app

1. Open ChatGPT desktop and sign in with the same ChatGPT Plus account.
2. Select **Codex** and open `C:\Github\aether-ai-os`.
3. Open **Settings → MCP servers → Add server**.
4. Configure:

```text
Name:
aether-operational

Type:
STDIO

Command:
C:\Github\aether-ai-os\.venv\Scripts\aether-mcp.exe
```

Environment:

```text
AETHER_PROJECT_ROOT=C:\Github\aether-ai-os
AETHER_HOME=C:\Users\hp\AppData\Local\Aether
```

Save and restart the server. Type `/mcp`; `aether-operational` must show as connected.

### Alternative: Codex CLI

```powershell
codex mcp add aether-operational `
    --env AETHER_PROJECT_ROOT=C:\Github\aether-ai-os `
    --env AETHER_HOME=C:\Users\hp\AppData\Local\Aether `
    -- C:\Github\aether-ai-os\.venv\Scripts\aether-mcp.exe

codex mcp list
```

The desktop app, CLI, and IDE extension share MCP configuration on the same Codex host.

## 5. Execute the bounded proof

Calculate the handoff digest:

```powershell
$ExpectedHandoffHash = (
    Get-FileHash `
        C:\Github\aether-ai-os\LASTSTANDINGPOINT.md `
        -Algorithm SHA256
).Hash.ToLowerInvariant()

$ExpectedHandoffHash
```

Send this prompt in a new Codex session, replacing `<EXPECTED_SHA256>`:

```text
Use only MCP server aether-operational for this proof.
Do not edit files, run shell commands, approve actions, or use mutation tools.

1. Enumerate its tools, resources, and prompts.
2. Call aether_status.
3. Read aether://handoff or call aether_handoff.
4. Call memory_search:
   query = "frozen laptop baseline"
   namespaces = ["episodes", "knowledge"]
   limit = 3
5. Call artifact_hash_verify:
   path = "LASTSTANDINGPOINT.md"
   expected_sha256 = "<EXPECTED_SHA256>"
6. Report returned schemas, security declarations, result counts,
   and whether the hash matched.
7. State that no mutation capability was available or used.
```

Expected exact surface:

```text
Resources:
aether://status
aether://capabilities
aether://handoff

Tools:
aether_status
aether_capability_manifest
aether_handoff
memory_search
artifact_hash_verify

Prompt:
aether_operational_context
```

Expected security truth:

```text
mode = read-only
mutation_tools = false
approval_decisions = false
arbitrary_file_reads = false
shell = false
legacy_cka_bulk_access = false
remote_http_default = false
```

A zero-result memory search is acceptable when the bounded call succeeds and reports truthfully.

## 6. Prove zero mutation

Repository:

```powershell
Set-Location C:\Github\aether-ai-os
git status --short
```

Expected: no output.

AETHER_HOME:

```powershell
$RepoRoot = "C:\Github\aether-ai-os"
$AetherHome = "$env:LOCALAPPDATA\Aether"
$ProofRoot = Join-Path $RepoRoot ".proof\mcp-founder"
$BeforePath = Join-Path $ProofRoot "aether-home-before.json"
$AfterPath = Join-Path $ProofRoot "aether-home-after.json"
$DiffPath = Join-Path $ProofRoot "aether-home-diff.json"

function Get-AetherManifest([string]$Root) {
    @(
        Get-ChildItem -LiteralPath $Root -Recurse -Force -File |
            Sort-Object FullName |
            ForEach-Object {
                [pscustomobject]@{
                    path = [IO.Path]::GetRelativePath(
                        $Root, $_.FullName
                    ).Replace("\", "/")
                    size_bytes = $_.Length
                    sha256 = (
                        Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256
                    ).Hash.ToLowerInvariant()
                }
            }
    )
}

$After = Get-AetherManifest $AetherHome
$After | ConvertTo-Json -Depth 4 |
    Set-Content -LiteralPath $AfterPath -Encoding UTF8

$Before = @(Get-Content $BeforePath -Raw | ConvertFrom-Json)
$BeforeMap = @{}
$AfterMap = @{}

foreach ($Item in $Before) {
    $BeforeMap[$Item.path] = "$($Item.size_bytes):$($Item.sha256)"
}
foreach ($Item in $After) {
    $AfterMap[$Item.path] = "$($Item.size_bytes):$($Item.sha256)"
}

$AllPaths = @($BeforeMap.Keys; $AfterMap.Keys) | Sort-Object -Unique
$Diff = @(
    foreach ($Path in $AllPaths) {
        $HasBefore = $BeforeMap.ContainsKey($Path)
        $HasAfter = $AfterMap.ContainsKey($Path)

        if (-not $HasBefore) {
            [pscustomobject]@{
                path=$Path; status="added"; before=$null; after=$AfterMap[$Path]
            }
        }
        elseif (-not $HasAfter) {
            [pscustomobject]@{
                path=$Path; status="removed"; before=$BeforeMap[$Path]; after=$null
            }
        }
        elseif ($BeforeMap[$Path] -ne $AfterMap[$Path]) {
            [pscustomobject]@{
                path=$Path; status="changed"
                before=$BeforeMap[$Path]; after=$AfterMap[$Path]
            }
        }
    }
)

$Diff | ConvertTo-Json -Depth 4 |
    Set-Content -LiteralPath $DiffPath -Encoding UTF8

if ($Diff.Count -ne 0) {
    $Diff | Format-Table -AutoSize
    throw "AETHER_HOME changed during the MCP proof."
}

Write-Host "PASS: AETHER_HOME is byte-for-byte unchanged."
```

## Founder acceptance

Pass only when:

```text
current main installed in a separate local clone
Codex local client connected over STDIO
exact capability enumeration passed
aether_status passed
aether_handoff passed
memory_search passed
artifact_hash_verify matched
Git working tree remained clean
AETHER_HOME before/after manifests are identical
```

Then classify Aether Operational MCP:

```text
IMPLEMENTED → WIRED → CONFORMED → ACTIVE → FOUNDER-PROVEN
```

This proof does not authorize mutation tools, public MCP ingress, remote OAuth, an external MCP client manager, or a generic MCP Builder.
