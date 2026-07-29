# IMPORTANT — Consolidated release

This file is retained for detailed Windows instructions. For this build, begin with `START_HERE_CONSOLIDATED.md`. Do not apply historical overlay ZIPs to this folder.

# Founder Start Here — Aether v0.19.2 on Windows VPS

**Canonical operating decision:** staged hybrid.

Aether is the cognitive operating system. AionUi is an optional operator shell. Aether does not depend on AionUi to boot, think, persist state, expose the Gateway, or serve Unified Browser Senses.

## Direct answer

On Windows, the Aether v0.19.2 release does **not** contain the full AionUi application.

It contains:

- Aether Core, Gateway, Tools, Browser Senses, and release wheels;
- Windows bring-up scripts;
- an `aionui-integration/` source patch pack.

It does **not** contain:

- the AionUi Windows installer;
- a prebuilt AionUi executable;
- an already-patched AionUi source checkout.

Therefore:

- You do **not** need AionUi to make Aether alive.
- You download/install AionUi separately only when you want its operator interface.
- The recommended Windows starting topology is hybrid, but brought up in two independent steps.

```text
Founder browser
  ├─ Aether Unified Senses  → http://127.0.0.1:8000/senses
  └─ AionUi WebUI          → http://127.0.0.1:25808

AionUi is replaceable.
Aether identity, memory, cognition, governance, and evolution remain in Aether.
```

---

# Which path should I use?

| Mode | Must install AionUi? | What you get | Use now? |
|---|---:|---|---:|
| **Aether-only** | No | Core, Gateway, APIs, `/senses`, deterministic pulse | **Yes — first boot** |
| **Hybrid Lite** | Yes, official Windows installer | Aether and AionUi run side-by-side; two browser URLs | **Yes — after Aether health** |
| **Hybrid Integrated** | Yes, source checkout/build | Aether `/senses` page appears inside AionUi at `/#/senses` | Later |
| Linux one-domain Compose | No manual AionUi install | Compose clones/builds AionUi automatically | Not the Windows path |

## Why not integrate everything before first boot?

Because that would make an optional operator shell a dependency of the cognitive core. It also multiplies the initial failure surface:

```text
Python + Aether
+ AionUi installer/source
+ AionCore backend
+ Bun/Node build
+ reverse proxy
+ Cloudflare
+ LiveKit
```

The executable-first sequence proves one layer at a time while preserving the final hybrid architecture.

---

# Tonight's exact run order

## Step 0 — Prepare the release folder

Recommended example:

```text
C:\Aether\Aether_OS_v0.19.2-unified-browser-senses\
```

Extract the canonical Aether v0.19.2 release there. Then copy the contents of this Windows overlay into the same directory.

At the end, the root must contain at least:

```text
AETHER_WINDOWS_READINESS.ps1
START_AETHER_WINDOWS_ALPHA.ps1
START_AIONUI_WINDOWS_LITE.ps1
aether-core\
aether-gateway\
aether-tools\
aionui-integration\
dist\
scripts\
```

Open **PowerShell** in that directory.


### Step 0.5 — Verify Python before running Aether

Aether v0.19.2 requires a real **64-bit Python 3.11 or newer interpreter**. The presence of `py.exe` alone is not sufficient; `py.exe` may exist while no Python runtime is installed.

Check:

```powershell
py -0p
py -3.11 --version
```

Accepted alternative:

```powershell
python --version
```

The reported version must be 3.11 or newer. If Python is newly installed, close PowerShell and open a new window so PATH and launcher registration are refreshed.

Do not use `START_AETHER.bat` or `FIRST_PULSE.bat` to bypass a Python error. Both ultimately require the same Python runtime.

## Step 1 — Prove Aether without AionUi

```powershell
Set-ExecutionPolicy -Scope Process Bypass

.\AETHER_WINDOWS_READINESS.ps1
.\START_AETHER_WINDOWS_ALPHA.ps1 -Action All
```

Expected result:

- virtual environment created;
- Aether wheels installed;
- `doctor` passes;
- deterministic first pulse passes;
- Gateway starts on port `8000`;
- evidence JSON and logs are written.

Open on the VPS:

```text
http://127.0.0.1:8000/senses
```

Check status later:

```powershell
.\START_AETHER_WINDOWS_ALPHA.ps1 -Action Status
```

Do not proceed because of a deadline if this stage is unhealthy. This is the smallest meaningful proof that Aether itself is alive.

## Step 2 — Add one live LLM provider

Edit:

```text
aether-core\.env
```

Add only one provider first. Keep all secret values on the VPS; do not paste them into chat logs.

Restart Aether:

```powershell
.\START_AETHER_WINDOWS_ALPHA.ps1 -Action Stop
.\START_AETHER_WINDOWS_ALPHA.ps1 -Action Start
```

Verify one real cognition turn before adding more providers or runtimes.

## Step 3 — Install AionUi only after Aether is healthy

Download the official **Windows x64 installer** from the AionUi GitHub Releases page and install it normally.

Official project:

```text
https://github.com/iOfficeAI/AionUi
```

Releases:

```text
https://github.com/iOfficeAI/AionUi/releases
```

The Windows installer includes AionUi's own backend. You do not need to download AionCore separately when using the official desktop installer.

## Step 4 — Start Hybrid Lite

Run:

```powershell
.\START_AIONUI_WINDOWS_LITE.ps1 -Action Start
```

The helper searches common installation locations and starts:

```text
AionUi.exe --webui --port 25808
```

Open:

```text
http://127.0.0.1:25808
```

On the first run, AionUi may generate an initial administrator password. The helper writes process output to:

```text
.aether-windows\aionui\aionui.stdout.log
.aether-windows\aionui\aionui.stderr.log
```

Check status:

```powershell
.\START_AIONUI_WINDOWS_LITE.ps1 -Action Status
```

Stop:

```powershell
.\START_AIONUI_WINDOWS_LITE.ps1 -Action Stop
```

At this point the system is intentionally side-by-side:

```text
Aether:  http://127.0.0.1:8000/senses
AionUi:  http://127.0.0.1:25808
```

This is already a valid hybrid runtime. AionUi is the UI; Aether remains the cognitive authority.

---

# What the `aionui-integration` folder actually does

The release folder:

```text
aionui-integration\
```

is **not an AionUi installer**.

It is a bounded source integration pack that copies Aether pages and safely wires the known `/senses` router anchors into an AionUi v2 source checkout.

The integration command is conceptually:

```powershell
.\.venv\Scripts\python.exe `
  .\aionui-integration\scripts\install_aionui_integration.py `
  C:\path\to\AionUi-source `
  --wire-router
```

That command requires an AionUi source checkout and a later AionUi build. It cannot modify an already-built `.exe` installer.

## What Hybrid Integrated adds

After a compatible AionUi source build is patched, the route becomes:

```text
http://host:25808/#/senses
```

The AionUi page embeds same-origin `/senses`, while Aether Gateway still owns:

- identity and DNA;
- memory;
- cognition;
- governance and approval;
- mission/execution state;
- CEE authority.

Hybrid Integrated is useful, but it is not required for the first VPS proof. It should be performed after the two independent services are healthy.

---

# Cloudflare and one-domain order

Do not configure public exposure before localhost acceptance.

Correct order:

```text
Aether localhost health
  → Aether real cognition
  → AionUi localhost health
  → Caddy local path routing
  → cloudflared tunnel
  → public HTTPS health
  → LiveKit microphone/speaker
  → camera keyframe
  → runtime body conformance
```

Final one-domain route:

```text
https://aether.example.com/            → AionUi :25808
https://aether.example.com/senses      → Aether Gateway :8000
https://aether.example.com/api/browser-senses/* → Aether Gateway :8000
https://aether.example.com/aether/*    → Aether Gateway :8000
```

The Windows overlay already contains a starter Caddyfile under:

```text
deploy\windows\Caddyfile
```

Caddy and cloudflared service installation remain a later deployment-adapter step; they are not required for the localhost first boot.

---

# Failure isolation

## Aether `/senses` fails, AionUi works

The problem is in Aether Gateway, its environment, provider configuration, or Browser Senses. Inspect:

```text
.aether-windows\logs\gateway.stdout.log
.aether-windows\logs\gateway.stderr.log
```

## Aether works, AionUi fails

Aether is still alive. Inspect:

```text
.aether-windows\aionui\aionui.stdout.log
.aether-windows\aionui\aionui.stderr.log
```

AionUi failure must not be diagnosed as Aether Core failure.

## Both work locally, public domain fails

The failure is in Caddy, cloudflared, DNS, or Cloudflare routing—not in Core cognition.

## `/#/senses` is missing in AionUi

This is expected in Hybrid Lite. The official prebuilt installer was not patched with the Aether source integration pack. Use the direct Aether URL or proceed later to Hybrid Integrated.

---

# Acceptance checklist

## Gate A — Aether alive

- [ ] Windows readiness passes.
- [ ] `doctor` passes.
- [ ] deterministic first pulse passes.
- [ ] `GET /api/status` returns healthy.
- [ ] `/senses` loads locally.

## Gate B — Hybrid Lite

- [ ] Official AionUi is installed.
- [ ] AionUi WebUI loads on port `25808`.
- [ ] Aether still loads independently on port `8000`.
- [ ] Restarting one does not destroy the other.

## Gate C — Public senses

- [ ] Caddy routes paths correctly.
- [ ] Cloudflare Tunnel is healthy.
- [ ] public HTTPS loads AionUi.
- [ ] public `/senses` reaches Aether.

## Gate D — Real embodiment

- [ ] live provider cognition succeeds.
- [ ] LiveKit microphone turn succeeds.
- [ ] spoken response succeeds.
- [ ] camera keyframe succeeds.
- [ ] one runtime body produces a conformance receipt.

Only after these gates should v0.20 begin.

---

# Canonical answer in one sentence

**Deploy Aether first without AionUi; then install AionUi separately and run both side-by-side; source-level AionUi integration is the final UI consolidation step, not a prerequisite for making Aether alive.**
