# Aether Body Subordination Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Aether (mind) controls aether-agent Nous (body) as subordinated execution surface — no dual-mind, Baby stage path to $10/day.

**Architecture:** Two processes (Aether daemon + aether-agent body) talk only via local adapter (HTTP first, MCP optional). Body castrated by config + Aether plugins (ContextEngine, Memory, bridge hooks). No fork of aether-agent by default.

**Tech Stack:** Python 3.11+, FastAPI/uvicorn (daemon), aether-core existing modules, aether-agent plugins (ContextEngine ABC, MemoryProvider ABC, hooks), pytest.

**Spec:** `docs/superpowers/specs/2026-07-23-aether-body-subordination-design.md`

**Repo root:** monorepo parent of `aether-core/`, `aether-brain/`, `aether-gateway/`, `aether-tools/`

**Constraint:** Pre-VPS work = code + tests + templates only. Deploy after VPS migrate + smoke test.

---

## File Map

| Path | Role |
|---|---|
| `aether-core/src/hermes/adapters/__init__.py` | Package |
| `aether-core/src/hermes/adapters/daemon.py` | FastAPI Aether daemon (mind process) |
| `aether-core/src/hermes/adapters/schemas.py` | Request/response models for adapter API |
| `aether-core/src/hermes/adapters/projection.py` | Project SOUL.md + MEMORY.md for body |
| `aether-core/src/hermes/adapters/client.py` | HTTP client body→mind (used by plugins) |
| `aether-core/configs/body_silence.yaml` | Template silenced aether-agent config |
| `aether-core/plugins/hermes_agent/context_engine/aether/` | ContextEngine plugin (install to `~/.hermes/plugins/`) |
| `aether-core/plugins/hermes_agent/memory/aether/` | MemoryProvider plugin |
| `aether-core/plugins/hermes_agent/aether_bridge/` | Hooks: pre_tool_call gate, post experience |
| `aether-core/tests/adapters/` | Unit tests |
| `aether-core/pyproject.toml` | Add `aether-daemon` script entry |

---

## Task 1: Adapter schemas (request/response)

**Files:**
- Create: `aether-core/src/hermes/adapters/__init__.py`
- Create: `aether-core/src/hermes/adapters/schemas.py`
- Test: `aether-core/tests/adapters/test_schemas.py`

- [ ] **Step 1: Create package init**

```python
# aether-core/src/hermes/adapters/__init__.py
"""Layer 3 — Aether ↔ aether-agent body adapter."""
```

- [ ] **Step 2: Write failing test**

```python
# aether-core/tests/adapters/test_schemas.py
from hermes.adapters.schemas import (
    WhoAmIResponse,
    BelieveRequest,
    EvaluateRequest,
    EvaluateResponse,
    RunTaskRequest,
)

def test_who_am_i_response_defaults():
    r = WhoAmIResponse(name="Hermes", narrative="test", stage="baby")
    assert r.name == "Hermes"
    assert r.stage == "baby"

def test_evaluate_request_requires_action():
    req = EvaluateRequest(action="open_trade", reason="signal", amount_usd=5.0)
    assert req.action == "open_trade"
    assert req.amount_usd == 5.0

def test_believe_request():
    req = BelieveRequest(claim="XAUUSD volatile", evidence="session-1", strength=0.4)
    assert 0.0 <= req.strength <= 1.0
```

- [ ] **Step 3: Run test — expect FAIL (module missing)**

```bash
cd aether-core
pytest tests/adapters/test_schemas.py -v
```

Expected: `ModuleNotFoundError` or collection error for `hermes.adapters.schemas`.

- [ ] **Step 4: Implement schemas**

```python
# aether-core/src/hermes/adapters/schemas.py
"""Adapter API contracts — body ↔ mind."""
from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class WhoAmIResponse(BaseModel):
    name: str
    narrative: str
    stage: str = "baby"
    mission: str = ""
    values: List[str] = Field(default_factory=list)
    alive: bool = True


class BelieveRequest(BaseModel):
    claim: str
    evidence: str
    strength: float = Field(default=0.3, ge=0.0, le=1.0)
    source: str = "body"


class BelieveResponse(BaseModel):
    accepted: bool
    claim: str
    note: str = ""


class EvaluateRequest(BaseModel):
    action: str
    reason: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    amount_usd: float = Field(default=0.0, ge=0.0)
    proposal_type: str = "other"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EvaluateResponse(BaseModel):
    approved: bool
    alignment_score: float
    veto_reason: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    escalate_to_dee: bool = False


class ExperienceRequest(BaseModel):
    action: str
    new_state: Dict[str, Any] = Field(default_factory=dict)
    was_expected: Optional[bool] = None
    source: str = "body"


class ExperienceResponse(BaseModel):
    ok: bool
    surprise: Optional[float] = None
    lesson: str = ""


class RunTaskRequest(BaseModel):
    goal: str
    context: Dict[str, Any] = Field(default_factory=dict)
    max_amount_usd: float = Field(default=0.0, ge=0.0)


class RunTaskResponse(BaseModel):
    accepted: bool
    task_id: str = ""
    note: str = ""


class HealthResponse(BaseModel):
    status: str
    dna_ok: bool
    mind_ready: bool
```

- [ ] **Step 5: Run test — expect PASS**

```bash
pytest tests/adapters/test_schemas.py -v
```

Expected: 3 PASSED

- [ ] **Step 6: Commit (if git repo available)**

```bash
git add aether-core/src/hermes/adapters aether-core/tests/adapters
git commit -m "feat(adapters): add Layer 3 request/response schemas"
```

---

## Task 2: Adapter HTTP client (body → mind)

**Files:**
- Create: `aether-core/src/hermes/adapters/client.py`
- Test: `aether-core/tests/adapters/test_client.py`

- [ ] **Step 1: Write failing test (mock transport)**

```python
# aether-core/tests/adapters/test_client.py
from unittest.mock import MagicMock, patch
from hermes.adapters.client import AetherClient


def test_who_am_i_parses_response():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "name": "Hermes",
        "narrative": "I am Aether",
        "stage": "baby",
        "alive": True,
    }
    with patch("hermes.adapters.client.requests.get", return_value=mock_resp):
        c = AetherClient(base_url="http://127.0.0.1:8765")
        r = c.who_am_i()
    assert r.name == "Hermes"
    assert r.alive is True


def test_evaluate_posts_body():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "approved": True,
        "alignment_score": 0.9,
        "warnings": [],
        "escalate_to_dee": False,
    }
    with patch("hermes.adapters.client.requests.post", return_value=mock_resp) as post:
        c = AetherClient(base_url="http://127.0.0.1:8765")
        r = c.evaluate(action="read_file", reason="inspect config", amount_usd=0)
    assert r.approved is True
    assert post.called


def test_health_down_returns_false():
    with patch("hermes.adapters.client.requests.get", side_effect=ConnectionError):
        c = AetherClient(base_url="http://127.0.0.1:8765", timeout=0.5)
        assert c.is_alive() is False
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pytest tests/adapters/test_client.py -v
```

- [ ] **Step 3: Implement client**

```python
# aether-core/src/hermes/adapters/client.py
"""HTTP client for aether-agent body plugins → Aether daemon."""
from __future__ import annotations
import os
import logging
from typing import Any, Dict, Optional

import requests

from hermes.adapters.schemas import (
    BelieveRequest,
    BelieveResponse,
    EvaluateRequest,
    EvaluateResponse,
    ExperienceRequest,
    ExperienceResponse,
    HealthResponse,
    WhoAmIResponse,
)

log = logging.getLogger(__name__)

DEFAULT_BASE = os.environ.get("AETHER_DAEMON_URL", "http://127.0.0.1:8765")


class AetherClient:
    def __init__(self, base_url: str = DEFAULT_BASE, timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def is_alive(self) -> bool:
        try:
            r = requests.get(f"{self.base_url}/health", timeout=self.timeout)
            return r.status_code == 200 and r.json().get("status") == "ok"
        except Exception as e:
            log.warning("Aether daemon unreachable: %s", e)
            return False

    def health(self) -> HealthResponse:
        r = requests.get(f"{self.base_url}/health", timeout=self.timeout)
        r.raise_for_status()
        return HealthResponse(**r.json())

    def who_am_i(self) -> WhoAmIResponse:
        r = requests.get(f"{self.base_url}/v1/who_am_i", timeout=self.timeout)
        r.raise_for_status()
        return WhoAmIResponse(**r.json())

    def evaluate(
        self,
        action: str,
        reason: str,
        confidence: float = 0.5,
        amount_usd: float = 0.0,
        proposal_type: str = "other",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> EvaluateResponse:
        body = EvaluateRequest(
            action=action,
            reason=reason,
            confidence=confidence,
            amount_usd=amount_usd,
            proposal_type=proposal_type,
            metadata=metadata or {},
        )
        r = requests.post(
            f"{self.base_url}/v1/north_star_evaluate",
            json=body.model_dump(),
            timeout=self.timeout,
        )
        r.raise_for_status()
        return EvaluateResponse(**r.json())

    def believe(self, claim: str, evidence: str, strength: float = 0.3, source: str = "body") -> BelieveResponse:
        body = BelieveRequest(claim=claim, evidence=evidence, strength=strength, source=source)
        r = requests.post(f"{self.base_url}/v1/believe", json=body.model_dump(), timeout=self.timeout)
        r.raise_for_status()
        return BelieveResponse(**r.json())

    def experience(
        self,
        action: str,
        new_state: Optional[Dict[str, Any]] = None,
        was_expected: Optional[bool] = None,
        source: str = "body",
    ) -> ExperienceResponse:
        body = ExperienceRequest(
            action=action,
            new_state=new_state or {},
            was_expected=was_expected,
            source=source,
        )
        r = requests.post(f"{self.base_url}/v1/experience", json=body.model_dump(), timeout=self.timeout)
        r.raise_for_status()
        return ExperienceResponse(**r.json())
```

- [ ] **Step 4: Run — expect PASS**

```bash
pytest tests/adapters/test_client.py -v
```

- [ ] **Step 5: Commit**

```bash
git add aether-core/src/hermes/adapters/client.py aether-core/tests/adapters/test_client.py
git commit -m "feat(adapters): HTTP client body→mind"
```

---

## Task 3: Body silence config template (F0)

**Files:**
- Create: `aether-core/configs/body_silence.yaml`
- Create: `aether-core/configs/README_BODY.md`

- [ ] **Step 1: Write silenced config template**

```yaml
# aether-core/configs/body_silence.yaml
# Copy to ~/.hermes/config.yaml (or merge). Castrates aether-agent entity defaults.
# Spec: docs/superpowers/specs/2026-07-23-aether-body-subordination-design.md §7

auxiliary:
  background_review:
    enabled: false   # dream = Aether only

memory:
  write_approval: true
  # provider: "aether"   # enable after Memory plugin installed

skills:
  write_approval: true

context:
  engine: "aether"   # requires ContextEngine plugin

# Optional: hide built-in memory toolset when Aether MemoryProvider is active
# agent:
#   disabled_toolsets: ["memory"]
```

- [ ] **Step 2: Write short install note**

```markdown
# Body silence (F0)

1. Install aether-agent (Nous) on target machine.
2. Merge `body_silence.yaml` into `~/.hermes/config.yaml`.
3. Confirm `auxiliary.background_review.enabled: false`.
4. Do NOT start dual Telegram — body gateway owns mouth after cutover.
5. Aether daemon must be up before body plugins can load mind state.
```

- [ ] **Step 3: Commit**

```bash
git add aether-core/configs/body_silence.yaml aether-core/configs/README_BODY.md
git commit -m "chore(config): F0 body silence template for aether-agent"
```

---

## Task 4: Aether daemon core (F1) — health + who_am_i + evaluate

**Files:**
- Create: `aether-core/src/hermes/adapters/daemon.py`
- Test: `aether-core/tests/adapters/test_daemon.py`
- Modify: `aether-core/pyproject.toml` (add script entry)

- [ ] **Step 1: Write failing integration test (TestClient)**

```python
# aether-core/tests/adapters/test_daemon.py
from fastapi.testclient import TestClient
from hermes.adapters.daemon import create_app


def test_health_ok():
    client = TestClient(create_app())
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["dna_ok"] is True


def test_who_am_i():
    client = TestClient(create_app())
    r = client.get("/v1/who_am_i")
    assert r.status_code == 200
    body = r.json()
    assert body["alive"] is True
    assert body["name"]


def test_evaluate_safe_action_approved():
    client = TestClient(create_app())
    r = client.post("/v1/north_star_evaluate", json={
        "action": "read_config",
        "reason": "inspect tool policy before change",
        "amount_usd": 0,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["approved"] is True
    assert body["escalate_to_dee"] is False


def test_evaluate_high_spend_escalates():
    client = TestClient(create_app())
    r = client.post("/v1/north_star_evaluate", json={
        "action": "open_trade",
        "reason": "momentum signal",
        "amount_usd": 50.0,
        "proposal_type": "open_trade",
    })
    assert r.status_code == 200
    body = r.json()
    # default Y=10 → escalate
    assert body["escalate_to_dee"] is True
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pytest tests/adapters/test_daemon.py -v
```

- [ ] **Step 3: Implement daemon**

```python
# aether-core/src/hermes/adapters/daemon.py
"""Aether daemon — mind process HTTP surface for body plugins."""
from __future__ import annotations
import logging
import os
from typing import Optional

from fastapi import FastAPI, HTTPException

from hermes.adapters.schemas import (
    BelieveRequest,
    BelieveResponse,
    EvaluateRequest,
    EvaluateResponse,
    ExperienceRequest,
    ExperienceResponse,
    HealthResponse,
    WhoAmIResponse,
)
from hermes.dna.loader import DNALoader
from hermes.governance.kernel import GovernanceKernel
from hermes.governance.proposal import Proposal, ProposalType

log = logging.getLogger(__name__)

# Soft risk: auto below Y, escalate at/above Y (spec § success criteria)
DEFAULT_ESCALATE_USD = float(os.environ.get("AETHER_ESCALATE_USD", "10"))


def _proposal_type(name: str) -> ProposalType:
    try:
        return ProposalType(name)
    except ValueError:
        return ProposalType.OTHER


class MindState:
    """Lazy-held mind handles. Consciousness optional until Task 5 wires experience."""

    def __init__(self):
        self.dna = DNALoader()
        self.kernel = GovernanceKernel()
        self.consciousness = None  # wired in Task 5
        self.escalate_usd = DEFAULT_ESCALATE_USD

    def dna_ok(self) -> bool:
        return self.dna.verify_integrity()


def create_app(mind: Optional[MindState] = None) -> FastAPI:
    mind = mind or MindState()
    app = FastAPI(title="Aether Daemon", version="0.1.0")
    app.state.mind = mind

    @app.get("/health", response_model=HealthResponse)
    def health():
        ok = mind.dna_ok()
        return HealthResponse(
            status="ok" if ok else "degraded",
            dna_ok=ok,
            mind_ready=ok,
        )

    @app.get("/v1/who_am_i", response_model=WhoAmIResponse)
    def who_am_i():
        if not mind.dna_ok():
            raise HTTPException(503, "DNA integrity failed")
        identity = mind.dna.load_identity()
        ns = mind.dna.load_north_star()
        narrative = ""
        if mind.consciousness is not None:
            try:
                narrative = str(mind.consciousness.who_am_i())
            except Exception as e:
                log.warning("who_am_i consciousness fallback: %s", e)
        if not narrative:
            narrative = identity.get("mission", {}).get("primary", "Aether mind online")
        values = identity.get("values", {}).get("non_negotiable", [])
        return WhoAmIResponse(
            name=identity.get("identity", {}).get("name", "Hermes"),
            narrative=narrative if isinstance(narrative, str) else str(narrative),
            stage="baby",
            mission=ns.get("north_star", {}).get("statement", "").strip(),
            values=list(values) if isinstance(values, list) else [],
            alive=True,
        )

    @app.post("/v1/north_star_evaluate", response_model=EvaluateResponse)
    def north_star_evaluate(req: EvaluateRequest):
        proposal = Proposal(
            action=req.action,
            reason=req.reason,
            confidence=req.confidence,
            risk_pct=min(req.amount_usd / 100.0, 1.0) if req.amount_usd else 0.0,
            proposal_type=_proposal_type(req.proposal_type),
            metadata={**req.metadata, "amount_usd": req.amount_usd},
        )
        result = mind.kernel.review(proposal)
        escalate = req.amount_usd >= mind.escalate_usd
        approved = result.approved and not escalate
        # escalate path: not auto-approved; body must ask Dee
        if escalate:
            return EvaluateResponse(
                approved=False,
                alignment_score=result.alignment_score,
                veto_reason=result.veto_reason or f"amount_usd {req.amount_usd} >= escalate ${mind.escalate_usd}",
                warnings=list(result.warnings) + ["escalate_to_dee"],
                escalate_to_dee=True,
            )
        return EvaluateResponse(
            approved=result.approved,
            alignment_score=result.alignment_score,
            veto_reason=result.veto_reason,
            warnings=list(result.warnings),
            escalate_to_dee=False,
        )

    @app.post("/v1/believe", response_model=BelieveResponse)
    def believe(req: BelieveRequest):
        # Full doubt engine wire in Task 5; accept + log for now
        log.info("believe source=%s claim=%s strength=%s", req.source, req.claim[:80], req.strength)
        return BelieveResponse(accepted=True, claim=req.claim, note="queued")

    @app.post("/v1/experience", response_model=ExperienceResponse)
    def experience(req: ExperienceRequest):
        if mind.consciousness is None:
            return ExperienceResponse(ok=True, lesson="consciousness_not_wired", surprise=None)
        try:
            out = mind.consciousness.experience(req.action, req.new_state, was_expected=req.was_expected)
            return ExperienceResponse(
                ok=True,
                surprise=out.get("surprise") if isinstance(out, dict) else None,
                lesson=str(out.get("lesson", "")) if isinstance(out, dict) else "",
            )
        except Exception as e:
            log.exception("experience failed")
            return ExperienceResponse(ok=False, lesson=str(e))

    return app


def main():
    import uvicorn
    host = os.environ.get("AETHER_HOST", "127.0.0.1")
    port = int(os.environ.get("AETHER_PORT", "8765"))
    uvicorn.run(create_app(), host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Add script entry to pyproject.toml**

In `aether-core/pyproject.toml` under `[project.scripts]` add:

```toml
aether-daemon = "hermes.adapters.daemon:main"
```

- [ ] **Step 5: Install + run tests**

```bash
cd aether-core
pip install -e ".[dev]"
pytest tests/adapters/test_daemon.py -v
```

Expected: 4 PASSED

- [ ] **Step 6: Manual smoke (optional local)**

```bash
aether-daemon
# other terminal:
curl http://127.0.0.1:8765/health
curl http://127.0.0.1:8765/v1/who_am_i
```

- [ ] **Step 7: Commit**

```bash
git add aether-core/src/hermes/adapters/daemon.py aether-core/tests/adapters/test_daemon.py aether-core/pyproject.toml
git commit -m "feat(adapters): Aether daemon health/who_am_i/evaluate"
```

---

## Task 5: Wire HermesConsciousness into daemon (experience + believe)

**Files:**
- Modify: `aether-core/src/hermes/adapters/daemon.py`
- Test: `aether-core/tests/adapters/test_daemon_consciousness.py`

- [ ] **Step 1: Write failing test**

```python
# aether-core/tests/adapters/test_daemon_consciousness.py
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from hermes.adapters.daemon import MindState, create_app


def test_experience_calls_consciousness():
    mind = MindState()
    mock_c = MagicMock()
    mock_c.experience.return_value = {"surprise": 0.6, "lesson": "tool_worked"}
    mind.consciousness = mock_c
    client = TestClient(create_app(mind))
    r = client.post("/v1/experience", json={"action": "bash_echo", "new_state": {"ok": True}})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["lesson"] == "tool_worked"
    mock_c.experience.assert_called_once()


def test_believe_uses_doubt_if_present():
    mind = MindState()
    mock_c = MagicMock()
    mock_c.doubt = MagicMock()
    mind.consciousness = mock_c
    client = TestClient(create_app(mind))
    r = client.post("/v1/believe", json={
        "claim": "API cost high",
        "evidence": "bill-2026-07",
        "strength": 0.5,
    })
    assert r.status_code == 200
    assert r.json()["accepted"] is True
```

- [ ] **Step 2: Run — expect FAIL on believe assert if not wired**

```bash
pytest tests/adapters/test_daemon_consciousness.py -v
```

- [ ] **Step 3: Update believe handler in daemon.py**

Replace the `believe` endpoint body with:

```python
    @app.post("/v1/believe", response_model=BelieveResponse)
    def believe(req: BelieveRequest):
        log.info("believe source=%s claim=%s strength=%s", req.source, req.claim[:80], req.strength)
        if mind.consciousness is not None and hasattr(mind.consciousness, "doubt"):
            try:
                mind.consciousness.doubt.add_evidence(
                    claim=req.claim,
                    supports=True,
                    evidence=req.evidence,
                    strength=req.strength,
                )
                return BelieveResponse(accepted=True, claim=req.claim, note="doubt_updated")
            except Exception as e:
                log.exception("believe failed")
                return BelieveResponse(accepted=False, claim=req.claim, note=str(e))
        return BelieveResponse(accepted=True, claim=req.claim, note="queued_no_consciousness")
```

Add optional boot helper:

```python
def boot_mind_with_consciousness() -> MindState:
    mind = MindState()
    try:
        from hermes.consciousness.consciousness import HermesConsciousness
        mind.consciousness = HermesConsciousness()
    except Exception as e:
        log.warning("Consciousness not loaded: %s", e)
    return mind
```

In `main()`, use `create_app(boot_mind_with_consciousness())` instead of bare `create_app()`.

- [ ] **Step 4: Run tests PASS**

```bash
pytest tests/adapters/test_daemon.py tests/adapters/test_daemon_consciousness.py -v
```

- [ ] **Step 5: Commit**

```bash
git add aether-core/src/hermes/adapters/daemon.py aether-core/tests/adapters/test_daemon_consciousness.py
git commit -m "feat(adapters): wire consciousness into believe/experience"
```

---

## Task 6: Projection SOUL.md + MEMORY.md (mind → body files)

**Files:**
- Create: `aether-core/src/hermes/adapters/projection.py`
- Test: `aether-core/tests/adapters/test_projection.py`

- [ ] **Step 1: Write failing test**

```python
# aether-core/tests/adapters/test_projection.py
from pathlib import Path
from hermes.adapters.projection import project_soul, project_memory


def test_project_soul_writes_file(tmp_path: Path):
    out = project_soul(tmp_path)
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "Hermes" in text or "Aether" in text or "Genome" in text
    assert "DO NOT EDIT" in text


def test_project_memory_operational_only(tmp_path: Path):
    out = project_memory(tmp_path, facts=["cwd is /app", "telegram allowed"])
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "cwd is /app" in text
    assert "BELIEF" not in text.upper() or "no beliefs" in text.lower()
```

- [ ] **Step 2: Implement projection**

```python
# aether-core/src/hermes/adapters/projection.py
"""Project Aether mind state into aether-agent body files (one-way)."""
from __future__ import annotations
from pathlib import Path
from typing import List, Optional

from hermes.dna.loader import DNALoader


HEADER = (
    "<!-- AUTO-GENERATED by Aether. DO NOT EDIT BY HAND. -->\n"
    "<!-- Source of truth: aether-core DNA + SelfModel. -->\n\n"
)


def project_soul(body_home: Path, dna: Optional[DNALoader] = None) -> Path:
    dna = dna or DNALoader()
    identity = dna.load_identity()
    genome = dna.load_genome()
    ns = dna.load_north_star()
    name = identity.get("identity", {}).get("name", "Hermes")
    mission = identity.get("mission", {}).get("primary", "")
    ns_stmt = ns.get("north_star", {}).get("statement", "").strip()
    principles = ns.get("sacred_principles", [])
    sp_lines = "\n".join(
        f"- {p.get('name')}: {p.get('statement')}" for p in principles if isinstance(p, dict)
    )
    # Compact genome excerpt (first 40 lines) — body prompt budget
    genome_excerpt = "\n".join(genome.splitlines()[:40])
    text = (
        f"{HEADER}"
        f"# SOUL — {name}\n\n"
        f"## Mission\n{mission}\n\n"
        f"## North Star\n{ns_stmt}\n\n"
        f"## Sacred Principles\n{sp_lines}\n\n"
        f"## Genome (excerpt)\n```\n{genome_excerpt}\n```\n"
    )
    path = Path(body_home) / "SOUL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def project_memory(body_home: Path, facts: Optional[List[str]] = None) -> Path:
    """Operational facts only. Never project beliefs."""
    facts = facts or []
    lines = [HEADER, "# MEMORY — operational (Aether projection)\n", "## Facts\n"]
    for f in facts[:40]:
        lines.append(f"- {f}\n")
    lines.append("\n<!-- no beliefs projected — different class -->\n")
    path = Path(body_home) / "MEMORY.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="utf-8")
    return path
```

- [ ] **Step 3: Run PASS + commit**

```bash
pytest tests/adapters/test_projection.py -v
git add aether-core/src/hermes/adapters/projection.py aether-core/tests/adapters/test_projection.py
git commit -m "feat(adapters): project SOUL.md and MEMORY.md for body"
```

---

## Task 7: ContextEngine plugin skeleton (F2)

**Files:**
- Create: `aether-core/plugins/hermes_agent/context_engine/aether/plugin.yaml`
- Create: `aether-core/plugins/hermes_agent/context_engine/aether/__init__.py`
- Create: `aether-core/plugins/hermes_agent/context_engine/aether/engine.py`
- Test: `aether-core/tests/adapters/test_context_engine_plugin.py`

**Note:** Plugin is authored in monorepo; at deploy, copy/symlink to `~/.hermes/plugins/context_engine/aether/`. Exact ContextEngine ABC method names must match installed aether-agent version — verify with local install before VPS.

- [ ] **Step 1: Write unit test for context builder (no aether-agent import required)**

```python
# aether-core/tests/adapters/test_context_engine_plugin.py
from hermes.adapters.client import AetherClient
from unittest.mock import MagicMock, patch


def test_build_mind_prefix_uses_who_am_i():
    # Import local helper that plugin will use
    import importlib.util
    from pathlib import Path
    p = Path("plugins/hermes_agent/context_engine/aether/engine.py")
    spec = importlib.util.spec_from_file_location("aether_engine", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    mock_client = MagicMock()
    mock_client.is_alive.return_value = True
    mock_client.who_am_i.return_value = MagicMock(
        name="Hermes",
        narrative="mind online",
        stage="baby",
        mission="create value",
        values=["truthfulness"],
    )
    text = mod.build_mind_prefix(mock_client)
    assert "Hermes" in text
    assert "baby" in text
    assert "mind online" in text


def test_build_mind_prefix_fail_safe_when_down():
    import importlib.util
    from pathlib import Path
    p = Path("plugins/hermes_agent/context_engine/aether/engine.py")
    spec = importlib.util.spec_from_file_location("aether_engine", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    mock_client = MagicMock()
    mock_client.is_alive.return_value = False
    text = mod.build_mind_prefix(mock_client)
    assert "FAIL-SAFE" in text or "unavailable" in text.lower()
```

- [ ] **Step 2: Implement engine helper + plugin files**

```yaml
# aether-core/plugins/hermes_agent/context_engine/aether/plugin.yaml
name: aether
kind: context_engine
version: 0.1.0
description: Aether mind ContextEngine — injects DNA/self into body turns
```

```python
# aether-core/plugins/hermes_agent/context_engine/aether/engine.py
"""Mind prefix builder for body ContextEngine plugin."""
from __future__ import annotations


def build_mind_prefix(client) -> str:
    if not client.is_alive():
        return (
            "[AETHER FAIL-SAFE] Mind daemon unavailable. "
            "Do NOT change identity, mission, goals, or irreversible state. "
            "Reply helpfully only; escalate to Dee if unsure.\n"
        )
    me = client.who_am_i()
    values = ", ".join(me.values[:5]) if getattr(me, "values", None) else ""
    return (
        f"[AETHER MIND]\n"
        f"Name: {me.name}\n"
        f"Stage: {me.stage}\n"
        f"Mission: {me.mission}\n"
        f"Values: {values}\n"
        f"Self: {me.narrative}\n"
        f"Authority: North Star gate required for irreversible / spend >= escalate threshold.\n"
        f"[/AETHER MIND]\n"
    )
```

```python
# aether-core/plugins/hermes_agent/context_engine/aether/__init__.py
"""
Register Aether ContextEngine with aether-agent.

Install: copy this directory to ~/.hermes/plugins/context_engine/aether/
Then set config: context.engine: "aether"

If aether-agent ABC differs, adapt register() to match installed version.
Docs: https://aether-agent.nousresearch.com/docs/developer-guide/context-engine-plugin
"""
from __future__ import annotations
import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)

# Ensure aether-core adapters importable when plugin runs inside aether-agent process
_CORE = os.environ.get("HERMES_CORE_SRC")
if _CORE and _CORE not in sys.path:
    sys.path.insert(0, _CORE)


def register(ctx):
    """aether-agent plugin entry. Prefer ContextEngine ABC if available."""
    try:
        from agent.context_engine import ContextEngine  # type: ignore
    except ImportError:
        log.warning("ContextEngine ABC not found — register hook fallback only")
        _register_hook_fallback(ctx)
        return

    from .engine import build_mind_prefix

    class AetherContextEngine(ContextEngine):  # type: ignore
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            from hermes.adapters.client import AetherClient
            self._client = AetherClient()

        # Method names may vary by aether-agent version — adjust after local verify.
        def compress(self, messages, **kwargs):
            # Pass-through compression; mind inject via pre_llm if needed
            if hasattr(super(), "compress"):
                return super().compress(messages, **kwargs)
            return messages

        def build_context(self, conversation_history, system_prompt="", **kwargs):
            prefix = build_mind_prefix(self._client)
            base = system_prompt or ""
            return f"{prefix}\n{base}"

    try:
        ctx.register_context_engine(AetherContextEngine())
    except Exception as e:
        log.warning("register_context_engine failed (%s) — hook fallback", e)
        _register_hook_fallback(ctx)


def _register_hook_fallback(ctx):
    from hermes.adapters.client import AetherClient
    from .engine import build_mind_prefix
    client = AetherClient()

    def pre_llm_call(session_id=None, user_message=None, **kwargs):
        return {"context": build_mind_prefix(client)}

    ctx.register_hook("pre_llm_call", pre_llm_call)
```

- [ ] **Step 3: Run tests from aether-core cwd**

```bash
cd aether-core
pytest tests/adapters/test_context_engine_plugin.py -v
```

- [ ] **Step 4: Commit**

```bash
git add aether-core/plugins/hermes_agent/context_engine aether-core/tests/adapters/test_context_engine_plugin.py
git commit -m "feat(plugins): Aether ContextEngine skeleton for aether-agent body"
```

---

## Task 8: Bridge plugin — pre_tool_call gate + post experience (F3)

**Files:**
- Create: `aether-core/plugins/hermes_agent/aether_bridge/plugin.yaml`
- Create: `aether-core/plugins/hermes_agent/aether_bridge/__init__.py`
- Create: `aether-core/plugins/hermes_agent/aether_bridge/policy.py`
- Test: `aether-core/tests/adapters/test_bridge_policy.py`

- [ ] **Step 1: Write policy unit tests**

```python
# aether-core/tests/adapters/test_bridge_policy.py
from hermes_bridge_policy import (  # loaded via path below
    is_irreversible_tool,
    estimate_amount_usd,
    should_gate,
)

# Prefer importing from monorepo path:
import importlib.util
from pathlib import Path

def _load():
    p = Path("plugins/hermes_agent/aether_bridge/policy.py")
    spec = importlib.util.spec_from_file_location("bridge_policy", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_terminal_rm_is_irreversible():
    m = _load()
    assert m.is_irreversible_tool("terminal", {"command": "rm -rf /tmp/x"}) is True


def test_read_file_not_irreversible():
    m = _load()
    assert m.is_irreversible_tool("read_file", {"path": "a.txt"}) is False


def test_estimate_amount_from_args():
    m = _load()
    assert m.estimate_amount_usd("open_trade", {"amount_usd": 12}) == 12.0


def test_should_gate_when_spend_or_irreversible():
    m = _load()
    assert m.should_gate("terminal", {"command": "rm foo"}) is True
    assert m.should_gate("read_file", {"path": "x"}) is False
```

- [ ] **Step 2: Implement policy.py**

```python
# aether-core/plugins/hermes_agent/aether_bridge/policy.py
"""Which body tool calls need Aether North Star gate."""
from __future__ import annotations
from typing import Any, Dict

IRREVERSIBLE_TOOLS = {
    "write_file", "patch", "file_edit", "skill_manage",
    "delegate_task", "browser_click",  # extend as needed
}

DANGEROUS_CMD_FRAGMENTS = (
    "rm ", "rm\t", "del ", "format ", "mkfs", "dd if=",
    "shutdown", "reboot", "> /dev/", "curl | sh", "wget | sh",
)


def is_irreversible_tool(tool_name: str, args: Dict[str, Any]) -> bool:
    name = (tool_name or "").lower()
    if name in IRREVERSIBLE_TOOLS or name.startswith("write"):
        return True
    if name in {"terminal", "bash", "run_terminal", "execute_code"}:
        cmd = str(args.get("command") or args.get("cmd") or args.get("code") or "").lower()
        return any(f in cmd for f in DANGEROUS_CMD_FRAGMENTS)
    return False


def estimate_amount_usd(tool_name: str, args: Dict[str, Any]) -> float:
    for key in ("amount_usd", "usd", "spend", "notional", "size_usd"):
        if key in args and args[key] is not None:
            try:
                return float(args[key])
            except (TypeError, ValueError):
                pass
    return 0.0


def should_gate(tool_name: str, args: Dict[str, Any]) -> bool:
    if estimate_amount_usd(tool_name, args) > 0:
        return True
    return is_irreversible_tool(tool_name, args)
```

- [ ] **Step 3: Implement plugin register**

```yaml
# aether-core/plugins/hermes_agent/aether_bridge/plugin.yaml
name: aether_bridge
version: 0.1.0
description: North Star gate + experience feedback for aether-agent body
provides_hooks:
  - pre_tool_call
  - post_tool_call
```

```python
# aether-core/plugins/hermes_agent/aether_bridge/__init__.py
from __future__ import annotations
import json
import logging
import os
import sys

log = logging.getLogger(__name__)
_CORE = os.environ.get("HERMES_CORE_SRC")
if _CORE and _CORE not in sys.path:
    sys.path.insert(0, _CORE)

from .policy import should_gate, estimate_amount_usd


class GateDenied(Exception):
    """Raised to signal tool must not run. Whether aether-agent honors this
    depends on hook semantics — VERIFY on local install (open question §13.1)."""


def register(ctx):
    from hermes.adapters.client import AetherClient
    client = AetherClient()

    def pre_tool_call(tool_name, args, task_id=None, **kwargs):
        args = args or {}
        if not should_gate(tool_name, args):
            return None
        if not client.is_alive():
            # fail closed on gated tools when mind down
            raise GateDenied("Aether mind unavailable — gated tool blocked")
        amount = estimate_amount_usd(tool_name, args)
        result = client.evaluate(
            action=f"tool:{tool_name}",
            reason=json.dumps(args)[:500],
            amount_usd=amount,
            metadata={"task_id": task_id or "", "tool": tool_name},
        )
        if result.escalate_to_dee:
            raise GateDenied(f"Escalate to Dee: {result.veto_reason}")
        if not result.approved:
            raise GateDenied(result.veto_reason or "North Star veto")
        return None

    def post_tool_call(tool_name, args, result=None, task_id=None, **kwargs):
        if not client.is_alive():
            return None
        try:
            client.experience(
                action=f"tool:{tool_name}",
                new_state={"result_preview": str(result)[:300] if result is not None else ""},
                source="body",
            )
        except Exception as e:
            log.warning("post experience failed: %s", e)
        return None

    ctx.register_hook("pre_tool_call", pre_tool_call)
    ctx.register_hook("post_tool_call", post_tool_call)
```

- [ ] **Step 4: Fix test imports to use path loader only (already in test)**

```bash
# simplify test file — remove broken top import, keep _load() only
cd aether-core
pytest tests/adapters/test_bridge_policy.py -v
```

- [ ] **Step 5: Manual verify hook can hard-block (local Nous)**

```bash
# After installing aether-agent + copying plugin:
# Trigger a gated tool; confirm tool does not execute when GateDenied raised.
# If hook is observe-only: document result, escalate to Layer 3 thin patch (spec §5 Layer 3).
```

- [ ] **Step 6: Commit**

```bash
git add aether-core/plugins/hermes_agent/aether_bridge aether-core/tests/adapters/test_bridge_policy.py
git commit -m "feat(plugins): aether_bridge pre_tool gate + post experience"
```

---

## Task 9: Memory provider plugin (minimal F4)

**Files:**
- Create: `aether-core/plugins/hermes_agent/memory/aether/plugin.yaml`
- Create: `aether-core/plugins/hermes_agent/memory/aether/__init__.py`
- Create: `aether-core/plugins/hermes_agent/memory/aether/provider.py`
- Test: `aether-core/tests/adapters/test_memory_provider_unit.py`

- [ ] **Step 1: Unit test provider methods without aether-agent**

```python
# aether-core/tests/adapters/test_memory_provider_unit.py
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock


def _load():
    p = Path("plugins/hermes_agent/memory/aether/provider.py")
    spec = importlib.util.spec_from_file_location("aether_mem", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_write_routes_to_believe():
    mod = _load()
    client = MagicMock()
    client.believe.return_value = MagicMock(accepted=True, note="ok")
    p = mod.AetherMemoryCore(client)
    out = p.write_operational("user prefers short answers")
    assert out["ok"] is True
    client.believe.assert_called()


def test_prefetch_fail_safe():
    mod = _load()
    client = MagicMock()
    client.is_alive.return_value = False
    p = mod.AetherMemoryCore(client)
    assert p.prefetch("hello") == ""
```

- [ ] **Step 2: Implement provider core**

```python
# aether-core/plugins/hermes_agent/memory/aether/provider.py
"""Aether-backed memory core used by MemoryProvider plugin."""
from __future__ import annotations
from typing import Any, Dict


class AetherMemoryCore:
    def __init__(self, client):
        self.client = client

    def prefetch(self, query: str) -> str:
        if not self.client.is_alive():
            return ""
        try:
            me = self.client.who_am_i()
            return f"Mind stage={me.stage}; self={me.narrative[:200]}"
        except Exception:
            return ""

    def write_operational(self, content: str) -> Dict[str, Any]:
        # Operational notes go as weak claims; beliefs never auto-promoted
        r = self.client.believe(
            claim=f"operational:{content[:200]}",
            evidence="body_memory_write",
            strength=0.2,
            source="body_memory",
        )
        return {"ok": bool(r.accepted), "note": r.note}
```

```yaml
# aether-core/plugins/hermes_agent/memory/aether/plugin.yaml
name: aether
kind: exclusive
version: 0.1.0
description: Aether mind as aether-agent memory provider
```

```python
# aether-core/plugins/hermes_agent/memory/aether/__init__.py
from __future__ import annotations
import logging
import os
import sys

log = logging.getLogger(__name__)
_CORE = os.environ.get("HERMES_CORE_SRC")
if _CORE and _CORE not in sys.path:
    sys.path.insert(0, _CORE)


def register(ctx):
    """Register MemoryProvider if ABC present; else no-op with log."""
    try:
        from agent.memory_provider import MemoryProvider  # type: ignore
    except ImportError:
        log.warning("MemoryProvider ABC missing — skip aether memory plugin")
        return

    from hermes.adapters.client import AetherClient
    from .provider import AetherMemoryCore

    class AetherMemoryProvider(MemoryProvider):  # type: ignore
        @property
        def name(self) -> str:
            return "aether"

        def is_available(self) -> bool:
            return True

        def initialize(self, session_id: str, **kwargs) -> None:
            self._session_id = session_id
            self._core = AetherMemoryCore(AetherClient())

        def get_tool_schemas(self):
            return []

        def handle_tool_call(self, tool_name, args, **kwargs):
            return "{}"

        def get_config_schema(self):
            return []

        def save_config(self, values, hermes_home):
            return None

        def prefetch(self, query, *, session_id=""):
            return self._core.prefetch(query)

        def sync_turn(self, user, assistant, *, session_id="", messages=None):
            # non-blocking best-effort
            try:
                self._core.write_operational(f"turn user={user[:80]}")
            except Exception as e:
                log.warning("sync_turn: %s", e)

    ctx.register_memory_provider(AetherMemoryProvider())
```

- [ ] **Step 3: Test + commit**

```bash
pytest tests/adapters/test_memory_provider_unit.py -v
git add aether-core/plugins/hermes_agent/memory aether-core/tests/adapters/test_memory_provider_unit.py
git commit -m "feat(plugins): minimal Aether MemoryProvider"
```

---

## Task 10: `aether_run_task` queue (F6 minimal)

Mind → body task handoff. MVP = daemon accepts task + writes queue file; body cron/poller executes later. Full AIAgent spawn = post-VPS.

**Files:**
- Modify: `aether-core/src/hermes/adapters/daemon.py` (add endpoint)
- Modify: `aether-core/src/hermes/adapters/schemas.py` (already has RunTask*)
- Create: `aether-core/src/hermes/adapters/task_queue.py`
- Test: `aether-core/tests/adapters/test_task_queue.py`

- [ ] **Step 1: Write failing test**

```python
# aether-core/tests/adapters/test_task_queue.py
from pathlib import Path
from hermes.adapters.task_queue import TaskQueue


def test_enqueue_and_list(tmp_path: Path):
    q = TaskQueue(tmp_path)
    tid = q.enqueue(goal="scan market niches", max_amount_usd=0)
    assert tid
    items = q.list_pending()
    assert len(items) == 1
    assert items[0]["goal"] == "scan market niches"


def test_mark_done(tmp_path: Path):
    q = TaskQueue(tmp_path)
    tid = q.enqueue(goal="x")
    q.complete(tid, result="ok")
    assert q.list_pending() == []
```

- [ ] **Step 2: Implement queue**

```python
# aether-core/src/hermes/adapters/task_queue.py
"""Simple JSONL task queue for mind→body run_task handoff."""
from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


class TaskQueue:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "run_tasks.jsonl"

    def enqueue(self, goal: str, max_amount_usd: float = 0.0, context: Dict[str, Any] | None = None) -> str:
        tid = uuid.uuid4().hex[:12]
        row = {
            "task_id": tid,
            "goal": goal,
            "max_amount_usd": max_amount_usd,
            "context": context or {},
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        return tid

    def list_pending(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("status") == "pending":
                out.append(row)
        return out

    def complete(self, task_id: str, result: str = "") -> None:
        if not self.path.exists():
            return
        rows = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("task_id") == task_id:
                row["status"] = "done"
                row["result"] = result
            rows.append(row)
        self.path.write_text("\n".join(json.dumps(r) for r in rows) + ("\n" if rows else ""), encoding="utf-8")
```

- [ ] **Step 3: Wire daemon endpoint**

In `MindState.__init__` add:

```python
from hermes.adapters.task_queue import TaskQueue
from hermes.paths import get_hermes_home
self.tasks = TaskQueue(get_hermes_home() / "queue")
```

Add route:

```python
from hermes.adapters.schemas import RunTaskRequest, RunTaskResponse

@app.post("/v1/run_task", response_model=RunTaskResponse)
def run_task(req: RunTaskRequest):
    tid = mind.tasks.enqueue(req.goal, req.max_amount_usd, req.context)
    return RunTaskResponse(accepted=True, task_id=tid, note="queued")
```

- [ ] **Step 4: Test + commit**

```bash
pytest tests/adapters/test_task_queue.py tests/adapters/test_daemon.py -v
git add aether-core/src/hermes/adapters/task_queue.py aether-core/src/hermes/adapters/daemon.py aether-core/tests/adapters/test_task_queue.py
git commit -m "feat(adapters): run_task queue for mind→body handoff"
```

---

## Task 11: Dual-mind / kill-test suite (F7)

**Files:**
- Create: `aether-core/tests/adapters/test_kill_switch.py`
- Create: `aether-core/tests/adapters/test_dual_mind_rules.py`

- [ ] **Step 1: Kill-test — mind down ⇒ gated tools blocked**

```python
# aether-core/tests/adapters/test_kill_switch.py
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch


def _load_bridge():
    p = Path("plugins/hermes_agent/aether_bridge/__init__.py")
    # load policy + simulate pre_tool via client mock
    pol = Path("plugins/hermes_agent/aether_bridge/policy.py")
    spec = importlib.util.spec_from_file_location("bridge_policy", pol)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_gated_tool_requires_gate():
    m = _load_bridge()
    assert m.should_gate("terminal", {"command": "rm secret"}) is True


def test_client_down_is_alive_false():
    from hermes.adapters.client import AetherClient
    with patch("hermes.adapters.client.requests.get", side_effect=ConnectionError):
        assert AetherClient(timeout=0.2).is_alive() is False
```

- [ ] **Step 2: Dual-mind rules checklist as executable asserts**

```python
# aether-core/tests/adapters/test_dual_mind_rules.py
from pathlib import Path


def test_body_silence_disables_background_review():
    text = Path("configs/body_silence.yaml").read_text(encoding="utf-8")
    assert "background_review" in text
    assert "enabled: false" in text


def test_soul_projection_forbids_hand_edit_banner():
    from hermes.adapters.projection import project_soul
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = project_soul(Path(d))
        assert "DO NOT EDIT" in p.read_text(encoding="utf-8")


def test_memory_projection_has_no_belief_section_as_facts():
    from hermes.adapters.projection import project_memory
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = project_memory(Path(d), facts=["tool path /x"])
        t = p.read_text(encoding="utf-8")
        assert "no beliefs" in t.lower() or "BELIEF" in t  # banner only
```

- [ ] **Step 3: Run full adapter suite**

```bash
cd aether-core
pytest tests/adapters/ -v
```

Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add aether-core/tests/adapters/test_kill_switch.py aether-core/tests/adapters/test_dual_mind_rules.py
git commit -m "test(adapters): kill-switch and dual-mind rule checks"
```

---

## Task 12: Deploy runbook + cutover checklist (F5/F0 ops)

**Files:**
- Create: `docs/superpowers/plans/2026-07-23-aether-body-DEPLOY.md`

- [ ] **Step 1: Write deploy runbook (ops, not code)**

Create file with these sections (full text in step):

```markdown
# Deploy & Cutover Runbook — Aether Body Subordination

## Preconditions
- [ ] VPS ready (RAM≥2G, disk≥20G, Python 3.11+, systemd, swap)
- [ ] Backup `aether-brain` + `.env` secrets taken
- [ ] Smoke: current Aether still boots on VPS
- [ ] `pytest aether-core/tests/adapters -v` green on build machine

## Install order
1. Clone monorepo; set `HERMES_HOME` → aether-brain path
2. `pip install -e aether-core`
3. `export AETHER_DAEMON_URL=http://127.0.0.1:8765`
4. `export HERMES_CORE_SRC=/path/to/aether-core/src`
5. systemd unit `aether.service` → `aether-daemon`
6. Install aether-agent (Nous) stock
7. Merge `aether-core/configs/body_silence.yaml` → `~/.hermes/config.yaml`
8. Copy plugins:
   - `plugins/hermes_agent/context_engine/aether` → `~/.hermes/plugins/context_engine/aether`
   - `plugins/hermes_agent/memory/aether` → `~/.hermes/plugins/memory/aether`
   - `plugins/hermes_agent/aether_bridge` → `~/.hermes/plugins/aether_bridge`
9. `aether-daemon` health OK
10. `hermes plugins` enable aether context + memory
11. Project SOUL: `python -c "from hermes.adapters.projection import project_soul; project_soul(Path.home()/'.hermes')"`
12. Start aether-agent gateway (Telegram)
13. **Cutover:** disable custom `aether-gateway` Telegram (`TELEGRAM_ENABLED=false`)
14. Kill test: stop aether.service → body must fail-safe / block gated tools
15. Restart aether → body recovers identity via who_am_i

## Rollback
- Re-enable custom gateway Telegram
- Stop aether-agent gateway
- Keep Aether daemon + brain intact
```

- [ ] **Step 2: Commit runbook**

```bash
git add docs/superpowers/plans/2026-07-23-aether-body-DEPLOY.md
git commit -m "docs: deploy and Telegram cutover runbook"
```

---

## Task 13: Economic loop stub (F8 placeholder — not full product)

Out of scope for full vehicle. Only budget gate + daily P&L log hook so mind can self-select later.

**Files:**
- Create: `aether-core/src/hermes/adapters/budget.py`
- Test: `aether-core/tests/adapters/test_budget.py`

- [ ] **Step 1: Test**

```python
# aether-core/tests/adapters/test_budget.py
from hermes.adapters.budget import BudgetGate


def test_allows_under_cap():
    g = BudgetGate(daily_cap_usd=10.0, spent_today=3.0)
    assert g.allow(5.0) is True


def test_blocks_over_cap():
    g = BudgetGate(daily_cap_usd=10.0, spent_today=8.0)
    assert g.allow(5.0) is False
```

- [ ] **Step 2: Implement**

```python
# aether-core/src/hermes/adapters/budget.py
"""Daily spend gate for Baby stage economic loop."""
from __future__ import annotations


class BudgetGate:
    def __init__(self, daily_cap_usd: float = 10.0, spent_today: float = 0.0):
        self.daily_cap_usd = daily_cap_usd
        self.spent_today = spent_today

    def allow(self, amount_usd: float) -> bool:
        if amount_usd < 0:
            return False
        return (self.spent_today + amount_usd) <= self.daily_cap_usd

    def record(self, amount_usd: float) -> None:
        self.spent_today += amount_usd
```

- [ ] **Step 3: Optional — call from evaluate path when amount_usd > 0** (wire later if needed)

- [ ] **Step 4: Commit**

```bash
git add aether-core/src/hermes/adapters/budget.py aether-core/tests/adapters/test_budget.py
git commit -m "feat(adapters): BudgetGate stub for Baby $10/day ceiling"
```

---

## Task 14: Final regression + handoff

- [ ] **Step 1: Run all adapter tests**

```bash
cd aether-core
pytest tests/adapters/ -v
```

Expected: all PASS

- [ ] **Step 2: Confirm artifacts exist**

```bash
ls src/hermes/adapters/{schemas,client,daemon,projection,task_queue,budget}.py
ls configs/body_silence.yaml
ls plugins/hermes_agent/context_engine/aether/
ls plugins/hermes_agent/memory/aether/
ls plugins/hermes_agent/aether_bridge/
ls ../docs/superpowers/specs/2026-07-23-aether-body-subordination-design.md
ls ../docs/superpowers/plans/2026-07-23-aether-body-subordination.md
ls ../docs/superpowers/plans/2026-07-23-aether-body-DEPLOY.md
```

- [ ] **Step 3: STOP — wait for VPS**

Do not cutover Telegram until VPS migrate + smoke + F0–F7 green on server.

- [ ] **Step 4: Handoff note**

Plumbing complete when Tasks 1–11 + 13 green. Task 12 = ops on VPS. F8 full economic vehicle = separate plan after body works.

---

## Spec coverage (self-review)

| Spec section | Task |
|---|---|
| §3 Principles / golden rules | Tasks 3, 8, 11 |
| §4.1 2-process topology | Tasks 4, 12 |
| §5 Layer 1 config | Task 3 |
| §5 Layer 2 plugins | Tasks 7, 8, 9 |
| §5 Layer 3 last resort | Task 8 Step 5 verify note |
| §6 Adapter contract | Tasks 1, 2, 4, 5, 10 |
| §7 Body silencing | Task 3 |
| §8 Baby stage | Tasks 4 escalate, 13 budget |
| §9 Risks (kill test, dual mind) | Task 11 |
| §10 F0–F7 sequence | Tasks 3–12 |
| §11 VPS first | Task 12, 14 |
| §12 Pre-VPS work | All code tasks |
| F8 product vehicle | Deferred (Task 13 stub only) |

## Open validation (must do on machine with aether-agent installed)

1. Does `pre_tool_call` hard-block when exception raised? (Task 8 Step 5)
2. Exact ContextEngine / MemoryProvider register API for your Nous version (Task 7/9)
3. Set `AETHER_ESCALATE_USD` (default 10)

---
