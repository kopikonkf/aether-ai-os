"""Founder acceptance packet and signed runtime proof."""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from aether.runtime.ingress import AetherCloudflareIngress
from aether.runtime.mcp import REQUIRED_AETHER_MCP_TOOLS
from aether.runtime.paths import AetherHome


ACCEPTANCE_SCHEMA = "aether.founder-acceptance.v1"
DEFAULT_SCOPE = "mvp-v0.20-preflight"
REQUIRED_SENSES_ROUTES = ("/health", "/api/browser-senses/status", "/senses")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _latest_receipt(path: Path, event: str) -> dict[str, Any] | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            receipt = dict(json.loads(line))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if receipt.get("event") == event:
            return receipt
    return None


def _criterion(criterion_id: str, label: str, status: str, detail: str, required: bool = True) -> dict[str, Any]:
    return {
        "id": criterion_id,
        "label": label,
        "required": required,
        "status": status,
        "detail": detail,
    }


@dataclass(frozen=True)
class FounderAcceptanceInput:
    founder_id: str
    attestation: str
    scope: str = DEFAULT_SCOPE
    evidence: dict[str, Any] | None = None
    allow_pending_evidence: bool = False


class FounderAcceptance:
    """Build acceptance evidence and persist explicit Founder sign-off."""

    def __init__(self, aether_home: Path | str | AetherHome):
        self.home = aether_home if isinstance(aether_home, AetherHome) else AetherHome(aether_home)
        self.home.ensure()

    def latest_record(self) -> dict[str, Any] | None:
        return _read_json(self.home.founder_acceptance_record)

    def state(self) -> dict[str, Any]:
        record = self.latest_record()
        return {
            "schema": ACCEPTANCE_SCHEMA,
            "founder_proven": bool(record and record.get("founder_proven")),
            "accepted": bool(record and record.get("accepted")),
            "decision": record.get("decision") if record else "pending",
            "scope": record.get("scope") if record else DEFAULT_SCOPE,
            "acceptance_id": record.get("acceptance_id") if record else None,
            "packet_id": record.get("packet_id") if record else None,
            "accepted_at": record.get("accepted_at") if record else None,
            "pending_evidence": record.get("pending_evidence", []) if record else [],
            "record_path": str(self.home.founder_acceptance_record),
        }

    def build_packet(
        self,
        *,
        runtime_health: Mapping[str, Any] | None = None,
        runtime_conformance: Mapping[str, Any] | None = None,
        evidence: Mapping[str, Any] | None = None,
        include_founder_attestation: bool = False,
    ) -> dict[str, Any]:
        evidence = evidence or {}
        criteria = [
            self._runtime_body_criterion(runtime_conformance),
            self._receipt_criterion(),
            self._tts_fallback_criterion(evidence),
            self._senses_criterion(evidence),
            self._mcp_activation_criterion(evidence),
            self._host_public_probe_criterion(evidence),
            self._google_live_tts_criterion(evidence),
            self._founder_attestation_criterion(include_founder_attestation),
        ]
        core = {
            "schema": ACCEPTANCE_SCHEMA,
            "scope": str(evidence.get("scope") or DEFAULT_SCOPE),
            "criteria": criteria,
            "evidence_summary": self._evidence_summary(runtime_health, runtime_conformance, evidence),
        }
        packet = {
            **core,
            "packet_id": _hash(core)[:24],
            "generated_at": _utc_now(),
            "acceptance_state": self.state(),
        }
        self.home.founder_acceptance_packet.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return packet

    def accept(
        self,
        request: FounderAcceptanceInput,
        *,
        runtime_health: Mapping[str, Any] | None = None,
        runtime_conformance: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        founder_id = request.founder_id.strip()
        attestation = request.attestation.strip()
        if not founder_id:
            raise ValueError("founder_id is required")
        if len(attestation) < 16:
            raise ValueError("attestation must be explicit")

        evidence = dict(request.evidence or {})
        evidence["scope"] = request.scope
        packet = self.build_packet(
            runtime_health=runtime_health,
            runtime_conformance=runtime_conformance,
            evidence=evidence,
            include_founder_attestation=True,
        )
        pending = [
            item["id"]
            for item in packet["criteria"]
            if item["required"] and item["status"] != "pass" and item["id"] != "founder_attestation"
        ]
        if pending and not request.allow_pending_evidence:
            return {
                "accepted": False,
                "decision": "blocked",
                "reason": "pending_required_evidence",
                "pending_evidence": pending,
                "packet": packet,
            }

        record = {
            "schema": ACCEPTANCE_SCHEMA,
            "acceptance_id": uuid.uuid4().hex,
            "packet_id": packet["packet_id"],
            "accepted_at": _utc_now(),
            "founder_id": founder_id,
            "scope": request.scope,
            "attestation_sha256": hashlib.sha256(attestation.encode("utf-8")).hexdigest(),
            "decision": "accepted_with_boundaries" if pending else "accepted",
            "accepted": True,
            "founder_proven": True,
            "pending_evidence": pending,
            "allow_pending_evidence": request.allow_pending_evidence,
            "packet": packet,
        }
        line = json.dumps(record, sort_keys=True)
        with self.home.founder_acceptance_log.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        self.home.founder_acceptance_record.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {
            "accepted": True,
            "decision": record["decision"],
            "founder_proven": True,
            "acceptance_id": record["acceptance_id"],
            "packet_id": record["packet_id"],
            "pending_evidence": pending,
            "record_path": str(self.home.founder_acceptance_record),
        }

    def _runtime_body_criterion(self, runtime_conformance: Mapping[str, Any] | None) -> dict[str, Any]:
        if not runtime_conformance:
            return _criterion("runtime_body_conformance", "One conformed runtime body", "pending", "No body conformance payload supplied.")
        ok = (
            runtime_conformance.get("conformed") is True
            and runtime_conformance.get("mutable_state") == "AETHER_HOME"
            and runtime_conformance.get("fail_safe_when_mind_down") is True
            and runtime_conformance.get("direct_mind_filesystem_writes") is False
        )
        return _criterion(
            "runtime_body_conformance",
            "One conformed runtime body",
            "pass" if ok else "fail",
            "Runtime body is subordinate, fail-safe, and AETHER_HOME-backed." if ok else "Runtime body conformance payload is incomplete.",
        )

    def _receipt_criterion(self) -> dict[str, Any]:
        try:
            exists = self.home.receipts.exists() and self.home.receipts.stat().st_size > 0
        except OSError:
            exists = False
        return _criterion(
            "runtime_receipts_present",
            "Runtime receipts exist",
            "pass" if exists else "pending",
            str(self.home.receipts) if exists else "No body receipts have been written yet.",
        )

    def _tts_fallback_criterion(self, evidence: Mapping[str, Any]) -> dict[str, Any]:
        tts_evidence = evidence.get("tts_audition") or evidence.get("tts_fallback_proof")
        if isinstance(tts_evidence, Mapping):
            provider = str(tts_evidence.get("provider") or "")
            fallback = bool(tts_evidence.get("fallback_used"))
            if provider and fallback:
                return _criterion("tts_fallback_proof", "Google TTS fallback proof", "pass", f"Fallback proof supplied by {provider}.")

        receipt = _latest_receipt(self.home.receipts, "tts.audition.completed")
        payload = receipt.get("payload", {}) if receipt else {}
        provider = str(payload.get("provider") or "")
        audio_path = Path(str(payload.get("audio_path") or "")) if payload.get("audio_path") else None
        audio_ok = False
        if audio_path:
            try:
                audio_ok = audio_path.exists() and (audio_path.read_bytes()[:4] in (b"RIFF", b"ID3\x03") or audio_path.stat().st_size > 16)
            except OSError:
                audio_ok = False
        fallback = bool(payload.get("fallback_used")) or provider == "local-wav-fallback"
        if provider and fallback and audio_ok:
            return _criterion("tts_fallback_proof", "Google TTS fallback proof", "pass", f"{provider} receipt and audio artifact verified.")
        return _criterion("tts_fallback_proof", "Google TTS fallback proof", "pending", "Run `/v1/body/tts/audition` with fallback or provide host evidence.")

    def _senses_criterion(self, evidence: Mapping[str, Any]) -> dict[str, Any]:
        status = evidence.get("browser_senses_status") or evidence.get("senses_public_health")
        if isinstance(status, Mapping):
            public_routes = status.get("gateway", {}).get("public_routes", []) if isinstance(status.get("gateway"), Mapping) else status.get("public_routes", [])
            routes = {str(route) for route in public_routes}
            route_ok = all(route in routes for route in REQUIRED_SENSES_ROUTES)
            ok = status.get("status") == "ok" and route_ok
            return _criterion(
                "aionui_senses_public_health",
                "AionUi/Senses public health",
                "pass" if ok else "fail",
                "Senses status route reports required public routes." if ok else "Senses status evidence is missing required routes.",
            )
        return _criterion("aionui_senses_public_health", "AionUi/Senses public health", "pending", "Provide `/api/browser-senses/status` evidence from Gateway.")

    def _mcp_activation_criterion(self, evidence: Mapping[str, Any]) -> dict[str, Any]:
        activation = evidence.get("mcp_activation") or _read_json(self.home.mcp_latest_activation)
        if isinstance(activation, Mapping):
            tools = {str(tool) for tool in activation.get("tools", [])}
            required = set(REQUIRED_AETHER_MCP_TOOLS)
            ok = activation.get("activated") is True and required.issubset(tools)
            return _criterion(
                "aether_mcp_activation",
                "Aether MCP activation",
                "pass" if ok else "fail",
                "MCP activation includes required Aether tools." if ok else "MCP activation is missing required tools.",
            )
        return _criterion("aether_mcp_activation", "Aether MCP activation", "pending", "Run `aether-mcp activate` or initialize the stdio MCP server.")

    def _host_public_probe_criterion(self, evidence: Mapping[str, Any]) -> dict[str, Any]:
        probe = evidence.get("public_host_probe") or evidence.get("cloudflare_ingress")
        if not isinstance(probe, Mapping):
            probe = AetherCloudflareIngress(self.home).latest_probe()
        if isinstance(probe, Mapping) and probe.get("status") == "ok":
            return _criterion("public_host_probe", "Cloudflare/one-domain public health", "pass", "Public host probe succeeded.", required=False)
        return _criterion("public_host_probe", "Cloudflare/one-domain public health", "pending", "Host HTTPS proof is still pending.", required=False)

    def _google_live_tts_criterion(self, evidence: Mapping[str, Any]) -> dict[str, Any]:
        tts = evidence.get("google_tts_live_audition")
        if isinstance(tts, Mapping) and tts.get("provider") == "google-cloud-tts" and tts.get("status") in {"completed", "ok"}:
            return _criterion("google_tts_live_audition", "Google TTS live audition", "pass", "Google Cloud TTS host audition succeeded.", required=False)
        return _criterion("google_tts_live_audition", "Google TTS live audition", "pending", "Credentialed Google audition not supplied.", required=False)

    def _founder_attestation_criterion(self, include_founder_attestation: bool) -> dict[str, Any]:
        record = self.latest_record()
        if include_founder_attestation or (record and record.get("accepted")):
            return _criterion("founder_attestation", "Founder attestation", "pass", "Founder acceptance record exists.")
        return _criterion("founder_attestation", "Founder attestation", "pending", "Founder has not signed this acceptance packet.")

    def _evidence_summary(
        self,
        runtime_health: Mapping[str, Any] | None,
        runtime_conformance: Mapping[str, Any] | None,
        evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "runtime_health_status": runtime_health.get("status") if runtime_health else None,
            "runtime_conformed": runtime_conformance.get("conformed") if runtime_conformance else None,
            "body_receipts_path": str(self.home.receipts),
            "tts_auditions_dir": str(self.home.tts_auditions),
            "mcp_activation_path": str(self.home.mcp_latest_activation),
            "cloudflare_ingress_probe_path": str(self.home.cloudflare_ingress_latest_probe),
            "evidence_keys": sorted(str(key) for key in evidence.keys()),
        }
