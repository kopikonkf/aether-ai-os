# Deploy & Cutover Runbook — Aether Body Subordination

**Target OS:** Linux (Debian/Ubuntu). Windows = local dev only.  
**Spec:** `docs/superpowers/specs/2026-07-23-aether-body-subordination-design.md`  
**Plan:** `docs/superpowers/plans/2026-07-23-aether-body-subordination.md`

---

## 0. VPS sizing

| Item | Min | Ideal |
|---|---|---|
| RAM | 2 GB | 4 GB |
| Disk | 20 GB | 40 GB |
| Swap | 2 GB | 4 GB |
| Python | 3.11+ | 3.12 |
| Init | systemd | systemd |

Two always-on processes: `aether.service` (mind) + aether-agent gateway (body).

---

## 1. Preconditions (before cutover)

- [ ] VPS ready (sizing above)
- [ ] Backup taken: `aether-brain/` entire tree + all `.env` / API keys / Telegram token
- [ ] `pytest tests/adapters/ -v` green on build machine (all adapter tests)
- [ ] DNA present: `aether-core/src/hermes/dna/{north_star.yaml,Genome.md,hermes.core.json}`
- [ ] Telegram bot token known; decide **one** mouth only after cutover

---

## 2. Migrate data (Genome R9)

```bash
# On old host: archive brain + secrets (do not put secrets in public git)
tar czf aether-brain-backup.tgz aether-brain/
# copy .env files offline

# On new VPS:
mkdir -p /opt/aether
# unpack monorepo + aether-brain under /opt/aether/
export HERMES_HOME=/opt/aether/aether-brain
export HERMES_CORE_SRC=/opt/aether/aether-core/src
export AETHER_DAEMON_URL=http://127.0.0.1:8765
export AETHER_ESCALATE_USD=10   # soft risk: auto below, escalate at/above
```

Smoke **before** body install:

```bash
cd /opt/aether/aether-core
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -c "from hermes.dna.loader import DNALoader; assert DNALoader().verify_integrity()"
```

---

## 3. Install order (mind first, then body)

### 3.1 Aether daemon (mind)

```bash
cd /opt/aether/aether-core
source .venv/bin/activate
pip install -e .
# CLI entry: aether-daemon
```

**systemd unit** `/etc/systemd/system/aether.service`:

```ini
[Unit]
Description=Aether mind daemon
After=network.target

[Service]
Type=simple
User=aether
WorkingDirectory=/opt/aether/aether-core
Environment=HERMES_HOME=/opt/aether/aether-brain
Environment=AETHER_HOST=127.0.0.1
Environment=AETHER_PORT=8765
Environment=AETHER_ESCALATE_USD=10
Environment=AETHER_DAEMON_URL=http://127.0.0.1:8765
ExecStart=/opt/aether/aether-core/.venv/bin/aether-daemon
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now aether.service
curl -s http://127.0.0.1:8765/health
curl -s http://127.0.0.1:8765/v1/who_am_i
```

Expect: `"status":"ok"`, `"dna_ok":true`, `"alive":true`.

### 3.2 aether-agent body (Nous stock)

```bash
# Install aether-agent per Nous docs (pip / official installer)
# Do NOT enable autonomous entity defaults — apply silence config next
```

### 3.3 Body silence (F0)

Merge `aether-core/configs/body_silence.yaml` into `~/.hermes/config.yaml` (body profile):

- `auxiliary.background_review.enabled: false`
- `memory.write_approval: true`
- `skills.write_approval: true`
- `context.engine: "aether"`

See also: `aether-core/configs/README_BODY.md`.

### 3.4 Install Aether plugins into body

```bash
# From monorepo
export HERMES_CORE_SRC=/opt/aether/aether-core/src
mkdir -p ~/.hermes/plugins/context_engine ~/.hermes/plugins/memory

cp -a /opt/aether/aether-core/plugins/hermes_agent/context_engine/aether \
      ~/.hermes/plugins/context_engine/aether
cp -a /opt/aether/aether-core/plugins/hermes_agent/memory/aether \
      ~/.hermes/plugins/memory/aether
cp -a /opt/aether/aether-core/plugins/hermes_agent/aether_bridge \
      ~/.hermes/plugins/aether_bridge

# Enable via hermes CLI if required by your Nous version:
# hermes plugins enable aether
# hermes plugins list
```

Body process **must** see:

```bash
export HERMES_CORE_SRC=/opt/aether/aether-core/src
export AETHER_DAEMON_URL=http://127.0.0.1:8765
```

### 3.5 Project SOUL (identity one-way)

```bash
source /opt/aether/aether-core/.venv/bin/activate
python -c "
from pathlib import Path
from hermes.adapters.projection import project_soul, project_memory
home = Path.home() / '.hermes'
project_soul(home)
project_memory(home, facts=['deployed on vps', 'telegram body mouth'])
print('projected to', home)
"
```

Confirm `~/.hermes/SOUL.md` contains `DO NOT EDIT`.

### 3.6 Start body gateway (Telegram mouth)

```bash
# hermes gateway start  (or equivalent for your Nous install)
# Use the SAME bot token you used for custom gateway
```

---

## 4. Cutover (one mouth)

1. Confirm body Telegram answers with mind context (who_am_i / self-consistent).
2. **Disable custom** `aether-gateway` Telegram:
   - `TELEGRAM_ENABLED=false` (or stop custom gateway service entirely)
3. Only aether-agent gateway holds the token.
4. Do **not** run dual Telegram adapters.

---

## 5. Kill test (must pass)

```bash
sudo systemctl stop aether.service
# Body: gated tools must fail-safe / block; no identity/goal decisions
# Chat may still reply helpfully with FAIL-SAFE prefix if ContextEngine loads

sudo systemctl start aether.service
curl -s http://127.0.0.1:8765/v1/who_am_i
# Body recovers mind identity
```

If gated tools still execute while mind is down → `pre_tool_call` is observe-only on this Nous version → Layer 3 thin patch (spec §5 Layer 3 / open question §13.1).

---

## 6. Rollback

| Step | Action |
|---|---|
| 1 | Stop aether-agent gateway |
| 2 | Re-enable custom `aether-gateway` + `TELEGRAM_ENABLED=true` |
| 3 | Keep `aether.service` + `HERMES_HOME` brain intact |
| 4 | Optional: leave plugins in place; they no-op if body not running |

---

## 7. Env cheat sheet

| Var | Who | Example |
|---|---|---|
| `HERMES_HOME` | mind | `/opt/aether/aether-brain` |
| `HERMES_CORE_SRC` | body plugins | `/opt/aether/aether-core/src` |
| `AETHER_DAEMON_URL` | body → mind | `http://127.0.0.1:8765` |
| `AETHER_HOST` / `AETHER_PORT` | mind bind | `127.0.0.1` / `8765` |
| `AETHER_ESCALATE_USD` | soft risk $Y | `10` |
| `TELEGRAM_BOT_TOKEN` | body only after cutover | (secret) |

Mind binds **localhost only**. Do not expose `:8765` publicly.

---

## 8. Health checks (daily)

```bash
systemctl is-active aether.service
curl -s http://127.0.0.1:8765/health | jq .
# Body: /status or hermes doctor equivalent
df -h; free -h
```

---

## 9. Out of scope here

- F8 full economic vehicle / niche product (`BudgetGate` stub only)
- Multi-platform beyond Telegram
- Forking aether-agent core (last resort only)

---

## 10. Sign-off

- [ ] Mind health OK
- [ ] who_am_i OK
- [ ] Body silence applied
- [ ] Plugins loaded
- [ ] SOUL projected
- [ ] Single Telegram mouth
- [ ] Kill test passed
- [ ] Rollback path known
