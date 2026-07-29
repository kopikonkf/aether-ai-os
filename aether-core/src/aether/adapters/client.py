"""HTTP client for aether-agent body plugins → Aether daemon."""
from __future__ import annotations
import os
import logging
from typing import Any, Dict, Optional

import requests

from aether.adapters.schemas import (
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
