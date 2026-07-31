"""One conformed Aether runtime body.

This is the smallest executable body contract: subordinate to the Aether mind,
fail-safe when the mind is down, persistent under AETHER_HOME, and receipted.
It does not wire a live provider or full external agent runtime yet. It exposes
a Google TTS audition surface with deterministic local fallback proof, but does
not claim full LiveKit voice routing. It also exposes local MCP activation
status and activation entrypoints for the Aether tool surface.
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib import error, request

from pydantic import BaseModel, Field

from aether.runtime.budget import PersistentBudgetGate
from aether.runtime.founder_acceptance import DEFAULT_SCOPE, FounderAcceptance, FounderAcceptanceInput
from aether.runtime.mvp20 import AetherMvp20Release, Mvp20EvidenceRequest
from aether.runtime.mcp import MCP_ACTIVATION_SCHEMA, REQUIRED_AETHER_MCP_TOOLS
from aether.runtime.paths import AetherHome, get_aether_home
from aether.runtime.tts import AetherTtsAudition, AetherTtsConfig


DEFAULT_MIND_URL = "http://127.0.0.1:8765"
DEFAULT_BODY_HOST = "127.0.0.1"
DEFAULT_BODY_PORT = 8780
DEFAULT_DAILY_CAP_USD = 10.0


class MindClient(Protocol):
    def is_alive(self) -> bool: ...

    def evaluate(
        self,
        action: str,
        reason: str,
        confidence: float = 0.5,
        amount_usd: float = 0.0,
        proposal_type: str = "other",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...


class HttpMindClient:
    """Minimal body-to-mind HTTP client."""

    def __init__(self, base_url: str = DEFAULT_MIND_URL, timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def is_alive(self) -> bool:
        try:
            with request.urlopen(f"{self.base_url}/health", timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
            return body.get("status") == "ok"
        except (OSError, error.URLError, json.JSONDecodeError):
            return False

    def evaluate(
        self,
        action: str,
        reason: str,
        confidence: float = 0.5,
        amount_usd: float = 0.0,
        proposal_type: str = "other",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "action": action,
            "reason": reason,
            "confidence": confidence,
            "amount_usd": amount_usd,
            "proposal_type": proposal_type,
            "metadata": metadata or {},
        }
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{self.base_url}/v1/north_star_evaluate",
            data=body,
            headers={"content-type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=self.timeout) as response:
            return dict(json.loads(response.read().decode("utf-8")))


class BodyRunRequest(BaseModel):
    goal: str
    context: dict[str, Any] = Field(default_factory=dict)
    max_amount_usd: float = Field(default=0.0, ge=0.0)
    irreversible: bool = False
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class BodyReceiptRequest(BaseModel):
    event: str
    payload: dict[str, Any] = Field(default_factory=dict)


class TtsAuditionRequest(BaseModel):
    text: str = Field(min_length=1, max_length=900)
    allow_external: bool | None = None
    language_code: str | None = None
    voice_name: str | None = None
    audio_encoding: str | None = None
    max_amount_usd: float = Field(default=0.0, ge=0.0)


class FounderAcceptanceRequest(BaseModel):
    founder_id: str = Field(min_length=1)
    attestation: str = Field(min_length=16)
    scope: str = DEFAULT_SCOPE
    evidence: dict[str, Any] = Field(default_factory=dict)
    allow_pending_evidence: bool = False


@dataclass(frozen=True)
class RuntimeBodyConfig:
    aether_home: Path
    mind_url: str
    profile: str = "aether-body"
    daily_cap_usd: float = DEFAULT_DAILY_CAP_USD
    host: str = DEFAULT_BODY_HOST
    port: int = DEFAULT_BODY_PORT

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "RuntimeBodyConfig":
        env = os.environ if environ is None else environ
        return cls(
            aether_home=Path(env.get("AETHER_HOME") or get_aether_home()),
            mind_url=env.get("AETHER_MIND_URL") or env.get("AETHER_DAEMON_URL") or DEFAULT_MIND_URL,
            profile=env.get("AETHER_BODY_PROFILE", "aether-body"),
            daily_cap_usd=float(env.get("AETHER_BODY_DAILY_CAP_USD", DEFAULT_DAILY_CAP_USD)),
            host=env.get("AETHER_BODY_HOST", DEFAULT_BODY_HOST),
            port=int(env.get("AETHER_BODY_PORT", str(DEFAULT_BODY_PORT))),
        )


class ConformedRuntimeBody:
    """Subordinate body runtime with persistent receipts."""

    def __init__(self, config: RuntimeBodyConfig, mind_client: MindClient | None = None):
        self.config = config
        self.home = AetherHome(config.aether_home)
        self.home.ensure()
        self.mind = mind_client or HttpMindClient(config.mind_url)
        self.budget = PersistentBudgetGate(self.home.budget_state, config.daily_cap_usd)
        self.tts = AetherTtsAudition(AetherTtsConfig.from_env(aether_home=config.aether_home))
        self.acceptance = FounderAcceptance(self.home)
        self.mvp20 = AetherMvp20Release(self.home)

    def mcp_status(self) -> dict[str, Any]:
        try:
            activation = json.loads(self.home.mcp_latest_activation.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            activation = None
        tools = activation.get("tools", []) if isinstance(activation, dict) else []
        required = set(REQUIRED_AETHER_MCP_TOOLS)
        active_required = required.issubset({str(tool) for tool in tools})
        return {
            "schema": MCP_ACTIVATION_SCHEMA,
            "activated": bool(isinstance(activation, dict) and activation.get("activated")),
            "required_tools_active": active_required,
            "transport": activation.get("transport") if isinstance(activation, dict) else "stdio-jsonrpc",
            "protocol_version": activation.get("protocol_version") if isinstance(activation, dict) else None,
            "tools": tools,
            "required_tools": list(REQUIRED_AETHER_MCP_TOOLS),
            "manifest_path": str(self.home.mcp_manifest),
            "activation_path": str(self.home.mcp_latest_activation),
            "receipts_path": str(self.home.mcp_receipts),
            "last_activation": activation,
        }

    def health(self) -> dict[str, Any]:
        mind_alive = self.mind.is_alive()
        return {
            "status": "ok" if mind_alive else "fail_safe",
            "body": "aether-runtime-body",
            "profile": self.config.profile,
            "authority": "subordinate_to_aether_mind",
            "mind_alive": mind_alive,
            "mind_url": self.config.mind_url,
            "aether_home": str(self.config.aether_home),
            "state_dir": str(self.home.body),
            "receipts_path": str(self.home.receipts),
            "budget": self.budget.snapshot().to_dict(),
            "tts": self.tts.status(),
            "founder_acceptance": self.acceptance.state(),
            "mcp": self.mcp_status(),
            "mvp20": self.mvp20.status(),
        }

    def _base_conformance(self) -> dict[str, Any]:
        health = self.health()
        mcp = health["mcp"]
        return {
            "conformed": True,
            "body": health["body"],
            "authority": health["authority"],
            "mutable_state": "AETHER_HOME",
            "mind_required": True,
            "fail_safe_when_mind_down": True,
            "direct_mind_filesystem_writes": False,
            "live_provider_wired": False,
            "voice_wired": False,
            "google_tts_audition": "source_present",
            "tts_fallback_proof": True,
            "tts_audition_endpoint": "/v1/body/tts/audition",
            "founder_acceptance_endpoint": "/v1/body/founder/acceptance",
            "mcp_activation": "activated" if mcp["activated"] and mcp["required_tools_active"] else "source_present",
            "mcp_required_tools_active": mcp["required_tools_active"],
            "mcp_transport": mcp["transport"],
            "mcp_command": "aether-mcp",
            "mcp_status_endpoint": "/v1/body/mcp/status",
            "receipts_path": health["receipts_path"],
        }

    def conformance(self) -> dict[str, Any]:
        conformance = self._base_conformance()
        acceptance = self.acceptance.state()
        conformance["founder_proven"] = acceptance["founder_proven"]
        conformance["founder_acceptance"] = acceptance
        conformance["mvp20_release"] = self.mvp20.status()
        return conformance

    def mvp20_status(self) -> dict[str, Any]:
        return self.mvp20.status()

    def mvp20_packet(self, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
        packet = self.mvp20.build_packet(
            runtime_health=self.health(),
            runtime_conformance=self._base_conformance(),
            evidence=evidence or {},
            persist=True,
        )
        receipt = self.record_receipt(
            "mvp20.packet.generated",
            {
                "packet_id": packet["packet_id"],
                "ready": packet["ready"],
                "state": packet["state"],
                "required_passed": packet["required_passed"],
                "required_total": packet["required_total"],
                "optional_passed": packet["optional_passed"],
                "optional_total": packet["optional_total"],
            },
        )
        packet["receipt_id"] = receipt["receipt_id"]
        return packet

    def founder_acceptance_packet(self, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.acceptance.build_packet(
            runtime_health=self.health(),
            runtime_conformance=self._base_conformance(),
            evidence=evidence or {},
        )

    def accept_founder_packet(self, request: FounderAcceptanceRequest) -> dict[str, Any]:
        result = self.acceptance.accept(
            FounderAcceptanceInput(
                founder_id=request.founder_id,
                attestation=request.attestation,
                scope=request.scope,
                evidence=request.evidence,
                allow_pending_evidence=request.allow_pending_evidence,
            ),
            runtime_health=self.health(),
            runtime_conformance=self._base_conformance(),
        )
        if result.get("accepted"):
            receipt = self.record_receipt(
                "founder.acceptance.recorded",
                {
                    "acceptance_id": result["acceptance_id"],
                    "packet_id": result["packet_id"],
                    "decision": result["decision"],
                    "pending_evidence": result["pending_evidence"],
                },
            )
            result["receipt_id"] = receipt["receipt_id"]
        else:
            receipt = self.record_receipt(
                "founder.acceptance.blocked",
                {
                    "reason": result.get("reason"),
                    "pending_evidence": result.get("pending_evidence", []),
                    "packet_id": result.get("packet", {}).get("packet_id"),
                },
            )
            result["receipt_id"] = receipt["receipt_id"]
        return result

    def record_receipt(self, event: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        receipt = {
            "receipt_id": uuid.uuid4().hex,
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "body": "aether-runtime-body",
            "profile": self.config.profile,
            "payload": payload or {},
        }
        line = json.dumps(receipt, sort_keys=True)
        self.home.receipts.parent.mkdir(parents=True, exist_ok=True)
        with self.home.receipts.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        self.home.latest_receipt.write_text(line + "\n", encoding="utf-8")
        return receipt

    def run(self, request: BodyRunRequest) -> dict[str, Any]:
        if not self.mind.is_alive():
            receipt = self.record_receipt(
                "body.run.refused",
                {"reason": "mind_unreachable_fail_safe", "goal": request.goal},
            )
            return {
                "accepted": False,
                "status": "fail_safe",
                "reason": "mind_unreachable_fail_safe",
                "receipt_id": receipt["receipt_id"],
            }

        if not self.budget.allow(request.max_amount_usd):
            receipt = self.record_receipt(
                "body.run.refused",
                {
                    "reason": "budget_cap_exceeded",
                    "goal": request.goal,
                    "max_amount_usd": request.max_amount_usd,
                    "budget": self.budget.snapshot().to_dict(),
                },
            )
            return {
                "accepted": False,
                "status": "blocked",
                "reason": "budget_cap_exceeded",
                "receipt_id": receipt["receipt_id"],
            }

        if request.irreversible or request.max_amount_usd > 0:
            try:
                decision = self.mind.evaluate(
                    action="body.run",
                    reason=request.goal,
                    confidence=request.confidence,
                    amount_usd=request.max_amount_usd,
                    proposal_type="run_task",
                    metadata={"context": request.context, "body_profile": self.config.profile},
                )
            except Exception as exc:
                receipt = self.record_receipt(
                    "body.run.refused",
                    {
                        "reason": "north_star_unreachable_fail_safe",
                        "goal": request.goal,
                        "error": str(exc),
                    },
                )
                return {
                    "accepted": False,
                    "status": "fail_safe",
                    "reason": "north_star_unreachable_fail_safe",
                    "receipt_id": receipt["receipt_id"],
                }
            if decision.get("escalate_to_dee") or not decision.get("approved", False):
                receipt = self.record_receipt(
                    "body.run.refused",
                    {
                        "reason": "north_star_gate",
                        "goal": request.goal,
                        "decision": decision,
                    },
                )
                return {
                    "accepted": False,
                    "status": "blocked",
                    "reason": "north_star_gate",
                    "receipt_id": receipt["receipt_id"],
                    "decision": decision,
                }

        budget = self.budget.record(request.max_amount_usd)
        receipt = self.record_receipt(
            "body.run.accepted",
            {
                "goal": request.goal,
                "context": request.context,
                "max_amount_usd": request.max_amount_usd,
                "budget": budget.to_dict(),
                "runtime_driver": "receipt_only",
            },
        )
        return {
            "accepted": True,
            "status": "queued",
            "runtime_driver": "receipt_only",
            "receipt_id": receipt["receipt_id"],
            "budget": budget.to_dict(),
        }

    def audition_tts(self, request: TtsAuditionRequest) -> dict[str, Any]:
        allow_external = self.tts.config.allow_external if request.allow_external is None else request.allow_external
        if allow_external and not self.mind.is_alive():
            receipt = self.record_receipt(
                "tts.audition.refused",
                {
                    "reason": "mind_unreachable_fail_safe",
                    "text_chars": len(request.text.strip()),
                    "allow_external": allow_external,
                },
            )
            return {
                "accepted": False,
                "status": "fail_safe",
                "reason": "mind_unreachable_fail_safe",
                "receipt_id": receipt["receipt_id"],
            }

        if request.max_amount_usd and not self.budget.allow(request.max_amount_usd):
            receipt = self.record_receipt(
                "tts.audition.refused",
                {
                    "reason": "budget_cap_exceeded",
                    "max_amount_usd": request.max_amount_usd,
                    "budget": self.budget.snapshot().to_dict(),
                },
            )
            return {
                "accepted": False,
                "status": "blocked",
                "reason": "budget_cap_exceeded",
                "receipt_id": receipt["receipt_id"],
            }

        if allow_external and request.max_amount_usd:
            try:
                decision = self.mind.evaluate(
                    action="tts.audition",
                    reason="Audition Google TTS voice for Aether body.",
                    confidence=0.8,
                    amount_usd=request.max_amount_usd,
                    proposal_type="voice_provider_audition",
                    metadata={
                        "language_code": request.language_code or self.tts.config.language_code,
                        "voice_name": request.voice_name or self.tts.config.voice_name,
                    },
                )
            except Exception as exc:
                receipt = self.record_receipt(
                    "tts.audition.refused",
                    {
                        "reason": "north_star_unreachable_fail_safe",
                        "error": str(exc),
                    },
                )
                return {
                    "accepted": False,
                    "status": "fail_safe",
                    "reason": "north_star_unreachable_fail_safe",
                    "receipt_id": receipt["receipt_id"],
                }
            if decision.get("escalate_to_dee") or not decision.get("approved", False):
                receipt = self.record_receipt(
                    "tts.audition.refused",
                    {
                        "reason": "north_star_gate",
                        "decision": decision,
                    },
                )
                return {
                    "accepted": False,
                    "status": "blocked",
                    "reason": "north_star_gate",
                    "receipt_id": receipt["receipt_id"],
                    "decision": decision,
                }

        result = self.tts.audition(
            request.text,
            allow_external=allow_external,
            language_code=request.language_code,
            voice_name=request.voice_name,
            audio_encoding=request.audio_encoding,
        )
        if request.max_amount_usd and result["provider"] == "google-cloud-tts":
            result["budget"] = self.budget.record(request.max_amount_usd).to_dict()
        return result


def create_app(body: ConformedRuntimeBody | None = None):
    from fastapi import FastAPI

    runtime_body = body or ConformedRuntimeBody(RuntimeBodyConfig.from_env())
    app = FastAPI(title="Aether Runtime Body", version="0.1.0")
    app.state.runtime_body = runtime_body

    @app.get("/health")
    def health() -> dict[str, Any]:
        return runtime_body.health()

    @app.get("/v1/body/health")
    def body_health() -> dict[str, Any]:
        return runtime_body.health()

    @app.get("/v1/body/conformance")
    def body_conformance() -> dict[str, Any]:
        return runtime_body.conformance()

    @app.post("/v1/body/run")
    def body_run(request: BodyRunRequest) -> dict[str, Any]:
        return runtime_body.run(request)

    @app.post("/v1/body/receipt")
    def body_receipt(request: BodyReceiptRequest) -> dict[str, Any]:
        return runtime_body.record_receipt(request.event, request.payload)

    @app.get("/v1/body/mcp/status")
    def body_mcp_status() -> dict[str, Any]:
        return runtime_body.mcp_status()

    @app.post("/v1/body/mcp/activate")
    def body_mcp_activate() -> dict[str, Any]:
        from aether.runtime.mcp import AetherMcpActivation, AetherMcpConfig

        activation = AetherMcpActivation(
            AetherMcpConfig(
                aether_home=runtime_body.config.aether_home,
                mind_url=runtime_body.config.mind_url,
            )
        )
        record = activation.activate()
        runtime_body.record_receipt("mcp.activation.requested", {"activation_id": record["activation_id"]})
        return record

    @app.post("/v1/body/tts/audition")
    def body_tts_audition(request: TtsAuditionRequest) -> dict[str, Any]:
        return runtime_body.audition_tts(request)

    @app.get("/v1/body/mvp20/status")
    def body_mvp20_status() -> dict[str, Any]:
        return runtime_body.mvp20_status()

    @app.post("/v1/body/mvp20/packet")
    def body_mvp20_packet(request: Mvp20EvidenceRequest) -> dict[str, Any]:
        return runtime_body.mvp20_packet(request.evidence)

    @app.get("/v1/body/founder/acceptance")
    def founder_acceptance() -> dict[str, Any]:
        return runtime_body.founder_acceptance_packet()

    @app.post("/v1/body/founder/acceptance")
    def founder_acceptance_accept(request: FounderAcceptanceRequest) -> dict[str, Any]:
        return runtime_body.accept_founder_packet(request)

    return app


def main() -> None:
    import uvicorn

    config = RuntimeBodyConfig.from_env()
    uvicorn.run(create_app(), host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    main()
