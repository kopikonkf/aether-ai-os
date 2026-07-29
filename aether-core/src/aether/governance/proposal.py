"""
Proposal Data Model for Aether Governance
==========================================
Defines Proposal, ProposalType, and ReviewResult.
"""

from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class ProposalType(str, Enum):
    OPEN_TRADE = "open_trade"
    CLOSE_TRADE = "close_trade"
    MODIFY_SYSTEM = "modify_system"
    DEPLOY_CODE = "deploy_code"
    UPDATE_BELIEF = "update_belief"
    EXECUTE_TASK = "execute_task"
    OTHER = "other"


class ReviewResult(BaseModel):
    approved: bool
    alignment_score: float = 1.0
    compounding_score: float = 1.0
    veto_reason: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)


class Proposal(BaseModel):
    action: str
    reason: str
    confidence: float = 0.5
    risk_pct: float = 0.0
    proposal_type: ProposalType = ProposalType.OTHER
    metadata: Dict[str, Any] = Field(default_factory=dict)
