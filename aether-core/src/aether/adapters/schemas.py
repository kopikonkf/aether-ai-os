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
