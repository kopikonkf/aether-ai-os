"""Aether daemon — mind process HTTP surface for body plugins."""
from __future__ import annotations
import logging
import os
from typing import Optional

from fastapi import FastAPI, HTTPException

from aether.adapters.schemas import (
    BelieveRequest,
    BelieveResponse,
    EvaluateRequest,
    EvaluateResponse,
    ExperienceRequest,
    ExperienceResponse,
    HealthResponse,
    RunTaskRequest,
    RunTaskResponse,
    WhoAmIResponse,
)
from aether.adapters.task_queue import TaskQueue
from aether.dna.loader import DNALoader
from aether.governance.kernel import GovernanceKernel
from aether.governance.proposal import Proposal, ProposalType
from aether.paths import get_aether_home

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
        self.tasks = TaskQueue(get_aether_home() / "queue")

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
            name=identity.get("identity", {}).get("name", "Aether"),
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

    @app.post("/v1/run_task", response_model=RunTaskResponse)
    def run_task(req: RunTaskRequest):
        tid = mind.tasks.enqueue(req.goal, req.max_amount_usd, req.context)
        return RunTaskResponse(accepted=True, task_id=tid, note="queued")

    return app


def boot_mind_with_consciousness() -> MindState:
    mind = MindState()
    try:
        from aether.consciousness.consciousness import AetherConsciousness
        mind.consciousness = AetherConsciousness()
    except Exception as e:
        log.warning("Consciousness not loaded: %s", e)
    return mind


def main():
    import uvicorn
    host = os.environ.get("AETHER_HOST", "127.0.0.1")
    port = int(os.environ.get("AETHER_PORT", "8765"))
    uvicorn.run(create_app(boot_mind_with_consciousness()), host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
