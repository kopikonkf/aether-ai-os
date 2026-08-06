"""MVP v0.20 governed shipping and measured demand packet."""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from pydantic import BaseModel, Field

from aether.runtime.ingress import AetherCloudflareIngress
from aether.runtime.paths import AetherHome


MVP20_SCHEMA = "aether.mvp.v0.20.release.v1"
MVP20_RELEASE_NAME = "MVP v0.20"
MVP20_RELEASE_TITLE = "Governed Shipping + Measured Demand Operations"
MVP20_SCOPE = "mvp-v0.20"
MVP20_ARCHITECTURE = (
    "Founder approval / release evidence",
    "validated private experiment",
    "consequence impact brief",
    "approval",
    "deployment adapter",
    "public promotion",
    "analytics and lead ledger",
    "verified demand and revenue linkage",
    "rollback / kill switch",
    "portfolio reallocation",
    "CEE strategy learning",
)
REQUIRED_PREPARE_CRITERIA = (
    "runtime_body_conformance",
    "tts_fallback_proof",
    "aionui_senses_public_health",
    "aether_mcp_activation",
    "founder_attestation",
)
REQUIRED_RELEASE_CRITERIA = (
    "validated_private_experiment",
    "consequence_impact_brief",
    "approval",
    "deployment_adapter",
    "public_promotion",
    "analytics_and_lead_ledger",
    "verified_demand_and_revenue_linkage",
    "rollback_and_kill_switch",
    "portfolio_reallocation",
    "cee_strategy_learning",
)
OPTIONAL_CRITERIA = ("public_host_probe", "google_tts_live_audition")
ACCEPTED_STATUS_VALUES = {
    "ok",
    "pass",
    "ready",
    "validated",
    "verified",
    "completed",
    "published",
    "armed",
    "wired",
    "written",
    "shared",
    "active",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _hash(value: Mapping[str, Any]) -> str:
    import hashlib

    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(data), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _append_jsonl(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(data), sort_keys=True, ensure_ascii=False) + "\n")


def _criterion(criterion_id: str, label: str, group: str, status: str, detail: str, required: bool = True) -> dict[str, Any]:
    return {
        "id": criterion_id,
        "label": label,
        "group": group,
        "required": required,
        "status": status,
        "detail": detail,
    }


def _status_value(data: Mapping[str, Any] | None) -> str:
    if not isinstance(data, Mapping):
        return ""
    status = data.get("status") or data.get("state") or data.get("mode") or data.get("phase")
    return str(status or "").strip().lower()


def _has_pass_status(data: Mapping[str, Any] | None, extra_truthy_keys: tuple[str, ...] = ()) -> bool:
    if not isinstance(data, Mapping):
        return False
    if _status_value(data) in ACCEPTED_STATUS_VALUES:
        return True
    return any(bool(data.get(key)) for key in extra_truthy_keys)


class Mvp20EvidenceRequest(BaseModel):
    evidence: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class Mvp20PacketSummary:
    schema: str
    release_name: str
    release_title: str
    state: str
    ready: bool
    packet_id: str | None
    packet_exists: bool
    packet_path: str
    required_passed: int
    required_total: int
    pending_required: list[str]
    optional_passed: int
    optional_total: int
    pending_optional: list[str]
    required_criteria: list[str]
    optional_criteria: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "release_name": self.release_name,
            "release_title": self.release_title,
            "state": self.state,
            "ready": self.ready,
            "packet_id": self.packet_id,
            "packet_exists": self.packet_exists,
            "packet_path": self.packet_path,
            "required_passed": self.required_passed,
            "required_total": self.required_total,
            "pending_required": list(self.pending_required),
            "optional_passed": self.optional_passed,
            "optional_total": self.optional_total,
            "pending_optional": list(self.pending_optional),
            "required_criteria": list(self.required_criteria),
            "optional_criteria": list(self.optional_criteria),
        }


class AetherMvp20Release:
    """Governed shipping and measured demand packet builder."""

    def __init__(self, aether_home: Path | str | AetherHome):
        self.home = aether_home if isinstance(aether_home, AetherHome) else AetherHome(aether_home)
        self.home.ensure()

    @property
    def release_dir(self) -> Path:
        return self.home.mvp20_release

    @property
    def packet_path(self) -> Path:
        return self.home.mvp20_latest_packet

    @property
    def log_path(self) -> Path:
        return self.home.mvp20_log

    def latest_packet(self) -> dict[str, Any] | None:
        return _read_json(self.packet_path)

    def status(self) -> dict[str, Any]:
        packet = self.latest_packet() or self.build_packet(persist=False)
        return self._summarize_packet(packet)

    def build_packet(
        self,
        *,
        runtime_health: Mapping[str, Any] | None = None,
        runtime_conformance: Mapping[str, Any] | None = None,
        evidence: Mapping[str, Any] | None = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        evidence = dict(evidence or {})
        criteria = [
            self._runtime_body_criterion(runtime_conformance),
            self._tts_fallback_criterion(runtime_conformance, evidence),
            self._senses_criterion(evidence),
            self._mcp_criterion(runtime_conformance, evidence),
            self._founder_criterion(runtime_conformance, evidence),
            self._validated_private_experiment_criterion(evidence),
            self._impact_brief_criterion(evidence),
            self._approval_criterion(evidence),
            self._deployment_adapter_criterion(evidence),
            self._public_promotion_criterion(evidence),
            self._analytics_and_lead_ledger_criterion(evidence),
            self._verified_demand_and_revenue_criterion(evidence),
            self._rollback_and_kill_switch_criterion(evidence),
            self._portfolio_reallocation_criterion(evidence),
            self._cee_strategy_learning_criterion(evidence),
            self._public_host_probe_criterion(evidence),
            self._google_tts_live_audition_criterion(evidence),
        ]
        required = [item for item in criteria if item["required"]]
        optional = [item for item in criteria if not item["required"]]
        required_passed = sum(1 for item in required if item["status"] == "pass")
        optional_passed = sum(1 for item in optional if item["status"] == "pass")
        ready = required_passed == len(required)
        state = "ready" if ready else "source-present"
        packet_core = {
            "schema": MVP20_SCHEMA,
            "release_name": MVP20_RELEASE_NAME,
            "release_title": MVP20_RELEASE_TITLE,
            "scope": str(evidence.get("scope") or MVP20_SCOPE),
            "generated_at": _utc_now(),
            "state": state,
            "ready": ready,
            "required_passed": required_passed,
            "required_total": len(required),
            "pending_required": [item["id"] for item in required if item["status"] != "pass"],
            "optional_passed": optional_passed,
            "optional_total": len(optional),
            "pending_optional": [item["id"] for item in optional if item["status"] != "pass"],
            "criteria": criteria,
            "evidence_summary": self._evidence_summary(runtime_health, runtime_conformance, evidence),
        }
        packet = {
            **packet_core,
            "packet_id": _hash(packet_core)[:24],
        }
        if persist:
            self._persist_packet(packet)
        return packet

    def render_laststandingpoint(self, packet: Mapping[str, Any] | None = None) -> str:
        packet = dict(packet or self.build_packet(persist=False))
        criteria = list(packet.get("criteria", []))
        state = str(packet.get("state") or "source-present")
        state_line = state if state == "ready" else f"{state}, host-proof pending"
        lines = [
            "# LAST STANDING POINT — Aether OS",
            "",
            f"**Canonical date:** {packet.get('generated_at', _utc_now())[:10]}",
            f"**Release:** {MVP20_RELEASE_NAME} — {MVP20_RELEASE_TITLE}",
            f"**State:** {state_line}",
            "",
            "## Canonical architecture",
            "",
            "```text",
            MVP20_ARCHITECTURE[0],
            *[f"  -> {item}" for item in MVP20_ARCHITECTURE[1:]],
            "```",
            "",
            "## Delivered in v0.20",
            "",
            "1. One conformed runtime body.",
            "2. Persistent `AETHER_HOME` budget state.",
            "3. Google TTS audition with deterministic fallback proof.",
            "4. AionUi/Senses public health surface.",
            "5. Aether MCP activation.",
            "6. Founder acceptance gate.",
            "7. Canonical release packet and LASTSTANDINGPOINT renderer.",
            "8. Persistent Windows service source harness with heartbeat/watchdog receipts.",
            "9. Cloudflare Tunnel ingress source harness with public probe receipts.",
            "",
            "## Packet",
            "",
            "| Criterion | Group | Status | Detail |",
            "|---|---|---|---|",
        ]
        for item in criteria:
            lines.append(
                f"| `{item['id']}` | {item['group']} | {item['status']} | {item['detail']} |"
            )
        lines.extend(
            [
                "",
                "## Verification",
                "",
                f"- Required passed: {packet.get('required_passed', 0)}/{packet.get('required_total', 0)}",
                f"- Optional passed: {packet.get('optional_passed', 0)}/{packet.get('optional_total', 0)}",
                f"- Packet id: `{packet.get('packet_id', '')}`",
                "",
                "## Honest boundaries",
                "",
                "- No real public promotion was executed from the build container.",
                "- No verified demand or revenue linkage was proven here.",
                "- No real rollback of a live deployment was performed here.",
                "- Host/browser proof still belongs on the Founder VPS and public domain.",
                "",
                "## Next operational step",
                "",
                "Run the first governed private experiment on the Founder host, capture the impact brief, promote it publicly, measure demand, and feed the results back into portfolio reallocation and CEE learning.",
            ]
        )
        return "\n".join(lines) + "\n"

    def write_laststandingpoint(self, output_path: Path, packet: Mapping[str, Any] | None = None) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(self.render_laststandingpoint(packet), encoding="utf-8")
        return output_path

    def _persist_packet(self, packet: Mapping[str, Any]) -> None:
        _write_json(self.packet_path, packet)
        _append_jsonl(self.log_path, {"event": "mvp20.packet.generated", **dict(packet)})

    def _summarize_packet(self, packet: Mapping[str, Any]) -> dict[str, Any]:
        criteria = list(packet.get("criteria", []))
        required = [item for item in criteria if item.get("required")]
        optional = [item for item in criteria if not item.get("required")]
        required_passed = sum(1 for item in required if item.get("status") == "pass")
        optional_passed = sum(1 for item in optional if item.get("status") == "pass")
        ready = bool(packet.get("ready"))
        state = str(packet.get("state") or ("ready" if ready else "source-present"))
        return Mvp20PacketSummary(
            schema=str(packet.get("schema") or MVP20_SCHEMA),
            release_name=str(packet.get("release_name") or MVP20_RELEASE_NAME),
            release_title=str(packet.get("release_title") or MVP20_RELEASE_TITLE),
            state=state,
            ready=ready,
            packet_id=str(packet.get("packet_id")) if packet.get("packet_id") else None,
            packet_exists=self.packet_path.exists(),
            packet_path=str(self.packet_path),
            required_passed=required_passed,
            required_total=len(required),
            pending_required=[item["id"] for item in required if item.get("status") != "pass"],
            optional_passed=optional_passed,
            optional_total=len(optional),
            pending_optional=[item["id"] for item in optional if item.get("status") != "pass"],
            required_criteria=list(REQUIRED_PREPARE_CRITERIA + REQUIRED_RELEASE_CRITERIA),
            optional_criteria=list(OPTIONAL_CRITERIA),
        ).to_dict()

    def _runtime_body_criterion(self, runtime_conformance: Mapping[str, Any] | None) -> dict[str, Any]:
        if not isinstance(runtime_conformance, Mapping):
            return _criterion(
                "runtime_body_conformance",
                "One conformed runtime body",
                "prepare",
                "pending",
                "No body conformance payload supplied.",
            )
        ok = (
            runtime_conformance.get("conformed") is True
            and runtime_conformance.get("mutable_state") == "AETHER_HOME"
            and runtime_conformance.get("fail_safe_when_mind_down") is True
            and runtime_conformance.get("direct_mind_filesystem_writes") is False
        )
        return _criterion(
            "runtime_body_conformance",
            "One conformed runtime body",
            "prepare",
            "pass" if ok else "fail",
            "Runtime body is subordinate, fail-safe, and AETHER_HOME-backed." if ok else "Runtime body conformance payload is incomplete.",
        )

    def _tts_fallback_criterion(
        self,
        runtime_conformance: Mapping[str, Any] | None,
        evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        if isinstance(runtime_conformance, Mapping) and runtime_conformance.get("tts_fallback_proof") is True:
            return _criterion(
                "tts_fallback_proof",
                "Google TTS audition and fallback proof",
                "prepare",
                "pass",
                "Runtime body reports TTS fallback proof.",
            )
        tts_evidence = evidence.get("tts_audition") or evidence.get("tts_fallback_proof")
        if isinstance(tts_evidence, Mapping):
            provider = str(tts_evidence.get("provider") or "")
            fallback = bool(tts_evidence.get("fallback_used"))
            audio_path = Path(str(tts_evidence.get("audio_path") or "")) if tts_evidence.get("audio_path") else None
            audio_ok = False
            if audio_path:
                try:
                    audio_ok = audio_path.exists() and audio_path.read_bytes().startswith(b"RIFF")
                except OSError:
                    audio_ok = False
            if provider and fallback and audio_ok:
                return _criterion(
                    "tts_fallback_proof",
                    "Google TTS audition and fallback proof",
                    "prepare",
                    "pass",
                    f"Fallback proof supplied by {provider}.",
                )
            return _criterion(
                "tts_fallback_proof",
                "Google TTS audition and fallback proof",
                "prepare",
                "fail",
                "Provided TTS evidence did not satisfy the fallback proof contract.",
            )
        return _criterion(
            "tts_fallback_proof",
            "Google TTS audition and fallback proof",
            "prepare",
            "pending",
            "Run `/v1/body/tts/audition` with fallback proof or provide host evidence.",
        )

    def _senses_criterion(self, evidence: Mapping[str, Any]) -> dict[str, Any]:
        status = evidence.get("browser_senses_status") or evidence.get("senses_public_health")
        if isinstance(status, Mapping):
            gateway = status.get("gateway") if isinstance(status.get("gateway"), Mapping) else {}
            public_routes = gateway.get("public_routes", []) if isinstance(gateway, Mapping) else status.get("public_routes", [])
            routes = {str(route) for route in public_routes}
            required_routes = {"/health", "/api/browser-senses/status", "/senses"}
            ok = status.get("status") == "ok" and required_routes.issubset(routes)
            return _criterion(
                "aionui_senses_public_health",
                "AionUi/Senses public health",
                "prepare",
                "pass" if ok else "fail",
                "Senses status route reports required public routes." if ok else "Senses status evidence is missing required routes.",
            )
        return _criterion(
            "aionui_senses_public_health",
            "AionUi/Senses public health",
            "prepare",
            "pending",
            "Provide `/api/browser-senses/status` evidence from Gateway.",
        )

    def _mcp_criterion(
        self,
        runtime_conformance: Mapping[str, Any] | None,
        evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        activation = evidence.get("mcp_activation")
        if isinstance(runtime_conformance, Mapping) and runtime_conformance.get("mcp_required_tools_active") is True:
            return _criterion(
                "aether_mcp_activation",
                "Aether MCP activation",
                "prepare",
                "pass",
                "Runtime body reports the required MCP tool set active.",
            )
        if isinstance(activation, Mapping):
            tools = {str(tool) for tool in activation.get("tools", [])}
            required = {
                "aether_who_am_i",
                "aether_north_star_evaluate",
                "aether_believe",
                "aether_sleep",
                "aether_run_task",
            }
            ok = activation.get("activated") is True and required.issubset(tools)
            return _criterion(
                "aether_mcp_activation",
                "Aether MCP activation",
                "prepare",
                "pass" if ok else "fail",
                "MCP activation includes required Aether tools." if ok else "MCP activation is missing required tools.",
            )
        return _criterion(
            "aether_mcp_activation",
            "Aether MCP activation",
            "prepare",
            "pending",
            "Run `aether-mcp activate` or initialize the stdio MCP server.",
        )

    def _founder_criterion(
        self,
        runtime_conformance: Mapping[str, Any] | None,
        evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        if isinstance(runtime_conformance, Mapping) and runtime_conformance.get("founder_proven") is True:
            return _criterion(
                "founder_attestation",
                "Founder attestation",
                "prepare",
                "pass",
                "Founder acceptance record exists.",
            )
        founder_record = evidence.get("founder_acceptance") or evidence.get("founder_attestation")
        if isinstance(founder_record, Mapping):
            accepted = founder_record.get("accepted") is True or founder_record.get("founder_proven") is True
            return _criterion(
                "founder_attestation",
                "Founder attestation",
                "prepare",
                "pass" if accepted else "fail",
                "Founder acceptance record exists." if accepted else "Founder evidence was supplied but not accepted.",
            )
        return _criterion(
            "founder_attestation",
            "Founder attestation",
            "prepare",
            "pending",
            "Founder has not signed the acceptance packet yet.",
        )

    def _validated_private_experiment_criterion(self, evidence: Mapping[str, Any]) -> dict[str, Any]:
        return self._mapping_criterion(
            "validated_private_experiment",
            "Validated private experiment",
            "release",
            evidence,
            key="private_experiment",
            accepted_statuses={"validated", "completed", "ready", "pass", "ok"},
            pending_detail="Provide a private experiment evidence packet.",
            pass_detail="Private experiment validated.",
            fail_detail="Private experiment evidence was supplied but not yet validated.",
        )

    def _impact_brief_criterion(self, evidence: Mapping[str, Any]) -> dict[str, Any]:
        return self._mapping_criterion(
            "consequence_impact_brief",
            "Consequence impact brief",
            "release",
            evidence,
            key="impact_brief",
            accepted_statuses={"written", "completed", "ready", "pass", "ok", "shared"},
            pending_detail="Provide the impact brief evidence packet.",
            pass_detail="Impact brief is recorded.",
            fail_detail="Impact brief evidence is present but not yet ready.",
        )

    def _approval_criterion(self, evidence: Mapping[str, Any]) -> dict[str, Any]:
        data = evidence.get("approval")
        if not isinstance(data, Mapping):
            return _criterion(
                "approval",
                "Approval",
                "release",
                "pending",
                "Provide an approval evidence packet.",
            )
        if bool(data.get("approved")) or _status_value(data) == "approved":
            return _criterion(
                "approval",
                "Approval",
                "release",
                "pass",
                "Release approval is recorded.",
            )
        return _criterion(
            "approval",
            "Approval",
            "release",
            "fail",
            "Approval evidence exists but is not approved.",
        )

    def _deployment_adapter_criterion(self, evidence: Mapping[str, Any]) -> dict[str, Any]:
        return self._mapping_criterion(
            "deployment_adapter",
            "Deployment adapter",
            "release",
            evidence,
            key="deployment_adapter",
            accepted_statuses={"wired", "ready", "completed", "pass", "ok"},
            pending_detail="Provide a deployment adapter evidence packet.",
            pass_detail="Deployment adapter is wired.",
            fail_detail="Deployment adapter evidence exists but is not ready.",
        )

    def _public_promotion_criterion(self, evidence: Mapping[str, Any]) -> dict[str, Any]:
        return self._mapping_criterion(
            "public_promotion",
            "Public promotion",
            "release",
            evidence,
            key="public_promotion",
            accepted_statuses={"published", "ready", "completed", "pass", "ok", "launched"},
            pending_detail="Provide public promotion evidence.",
            pass_detail="Public promotion is recorded.",
            fail_detail="Promotion evidence is present but not published.",
        )

    def _analytics_and_lead_ledger_criterion(self, evidence: Mapping[str, Any]) -> dict[str, Any]:
        analytics = evidence.get("analytics")
        lead_ledger = evidence.get("lead_ledger")
        if not isinstance(analytics, Mapping) or not isinstance(lead_ledger, Mapping):
            return _criterion(
                "analytics_and_lead_ledger",
                "Analytics and lead ledger",
                "release",
                "pending",
                "Provide analytics and lead ledger evidence.",
            )
        analytics_ok = _has_pass_status(analytics, extra_truthy_keys=("events", "metrics", "rows"))
        leads_ok = _has_pass_status(lead_ledger, extra_truthy_keys=("leads", "entries", "count"))
        if analytics_ok and leads_ok:
            return _criterion(
                "analytics_and_lead_ledger",
                "Analytics and lead ledger",
                "release",
                "pass",
                "Analytics and lead ledger are recorded.",
            )
        return _criterion(
            "analytics_and_lead_ledger",
            "Analytics and lead ledger",
            "release",
            "fail",
            "Analytics or lead ledger evidence is incomplete.",
        )

    def _verified_demand_and_revenue_criterion(self, evidence: Mapping[str, Any]) -> dict[str, Any]:
        demand = evidence.get("demand")
        revenue = evidence.get("revenue_linkage")
        if not isinstance(demand, Mapping) or not isinstance(revenue, Mapping):
            return _criterion(
                "verified_demand_and_revenue_linkage",
                "Verified demand and revenue linkage",
                "release",
                "pending",
                "Provide demand and revenue linkage evidence.",
            )
        demand_ok = _has_pass_status(demand, extra_truthy_keys=("verified", "signals", "demand_score"))
        revenue_ok = _has_pass_status(revenue, extra_truthy_keys=("linked", "revenue", "rows"))
        if demand_ok and revenue_ok:
            return _criterion(
                "verified_demand_and_revenue_linkage",
                "Verified demand and revenue linkage",
                "release",
                "pass",
                "Demand and revenue linkage are verified.",
            )
        return _criterion(
            "verified_demand_and_revenue_linkage",
            "Verified demand and revenue linkage",
            "release",
            "fail",
            "Demand or revenue linkage evidence is incomplete.",
        )

    def _rollback_and_kill_switch_criterion(self, evidence: Mapping[str, Any]) -> dict[str, Any]:
        rollback = evidence.get("rollback")
        kill_switch = evidence.get("kill_switch")
        if not isinstance(rollback, Mapping) or not isinstance(kill_switch, Mapping):
            return _criterion(
                "rollback_and_kill_switch",
                "Rollback and kill switch",
                "release",
                "pending",
                "Provide rollback and kill switch evidence.",
            )
        rollback_ok = _has_pass_status(rollback, extra_truthy_keys=("armed", "available", "ready"))
        kill_ok = _has_pass_status(kill_switch, extra_truthy_keys=("armed", "enabled", "ready"))
        if rollback_ok and kill_ok:
            return _criterion(
                "rollback_and_kill_switch",
                "Rollback and kill switch",
                "release",
                "pass",
                "Rollback and kill switch are armed.",
            )
        return _criterion(
            "rollback_and_kill_switch",
            "Rollback and kill switch",
            "release",
            "fail",
            "Rollback or kill switch evidence is incomplete.",
        )

    def _portfolio_reallocation_criterion(self, evidence: Mapping[str, Any]) -> dict[str, Any]:
        return self._mapping_criterion(
            "portfolio_reallocation",
            "Portfolio reallocation",
            "release",
            evidence,
            key="portfolio_reallocation",
            accepted_statuses={"ready", "completed", "pass", "ok", "applied"},
            pending_detail="Provide portfolio reallocation evidence.",
            pass_detail="Portfolio reallocation is recorded.",
            fail_detail="Portfolio reallocation evidence exists but is not ready.",
        )

    def _cee_strategy_learning_criterion(self, evidence: Mapping[str, Any]) -> dict[str, Any]:
        return self._mapping_criterion(
            "cee_strategy_learning",
            "CEE strategy learning",
            "release",
            evidence,
            key="strategy_learning",
            accepted_statuses={"ready", "completed", "pass", "ok", "captured"},
            pending_detail="Provide CEE strategy learning evidence.",
            pass_detail="CEE strategy learning is captured.",
            fail_detail="Strategy learning evidence exists but is not yet complete.",
        )

    def _public_host_probe_criterion(self, evidence: Mapping[str, Any]) -> dict[str, Any]:
        probe = evidence.get("public_host_probe") or evidence.get("cloudflare_ingress")
        if not isinstance(probe, Mapping):
            probe = AetherCloudflareIngress(self.home).latest_probe()
        if not isinstance(probe, Mapping):
            return _criterion(
                "public_host_probe",
                "Cloudflare/one-domain public health",
                "optional",
                "pending",
                "Host HTTPS proof is still pending.",
                required=False,
            )
        if probe.get("status") == "ok":
            return _criterion(
                "public_host_probe",
                "Cloudflare/one-domain public health",
                "optional",
                "pass",
                "Public host probe succeeded.",
                required=False,
            )
        return _criterion(
            "public_host_probe",
            "Cloudflare/one-domain public health",
            "optional",
            "fail",
            "Public host probe evidence was supplied but did not pass.",
            required=False,
        )

    def _google_tts_live_audition_criterion(self, evidence: Mapping[str, Any]) -> dict[str, Any]:
        tts = evidence.get("google_tts_live_audition")
        if not isinstance(tts, Mapping):
            return _criterion(
                "google_tts_live_audition",
                "Google TTS live audition",
                "optional",
                "pending",
                "Credentialed Google audition not supplied.",
                required=False,
            )
        if tts.get("provider") == "google-cloud-tts" and tts.get("status") in {"completed", "ok", "ready"}:
            return _criterion(
                "google_tts_live_audition",
                "Google TTS live audition",
                "optional",
                "pass",
                "Google Cloud TTS host audition succeeded.",
                required=False,
            )
        return _criterion(
            "google_tts_live_audition",
            "Google TTS live audition",
            "optional",
            "fail",
            "Google audition evidence exists but is not ready.",
            required=False,
        )

    def _mapping_criterion(
        self,
        criterion_id: str,
        label: str,
        group: str,
        evidence: Mapping[str, Any],
        *,
        key: str,
        accepted_statuses: set[str],
        pending_detail: str,
        pass_detail: str,
        fail_detail: str,
        required: bool = True,
    ) -> dict[str, Any]:
        raw = evidence.get(key)
        if not isinstance(raw, Mapping):
            return _criterion(criterion_id, label, group, "pending", pending_detail, required=required)
        if _status_value(raw) in accepted_statuses or any(bool(raw.get(k)) for k in ("approved", "validated", "verified", "published", "armed", "ready", "pass")):
            return _criterion(criterion_id, label, group, "pass", pass_detail, required=required)
        return _criterion(criterion_id, label, group, "fail", fail_detail, required=required)

    def _evidence_summary(
        self,
        runtime_health: Mapping[str, Any] | None,
        runtime_conformance: Mapping[str, Any] | None,
        evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "runtime_health_status": runtime_health.get("status") if isinstance(runtime_health, Mapping) else None,
            "runtime_conformed": runtime_conformance.get("conformed") if isinstance(runtime_conformance, Mapping) else None,
            "founder_proven": runtime_conformance.get("founder_proven") if isinstance(runtime_conformance, Mapping) else None,
            "mcp_required_tools_active": runtime_conformance.get("mcp_required_tools_active") if isinstance(runtime_conformance, Mapping) else None,
            "tts_fallback_proof": runtime_conformance.get("tts_fallback_proof") if isinstance(runtime_conformance, Mapping) else None,
            "evidence_keys": sorted(str(key) for key in evidence.keys()),
            "release_dir": str(self.release_dir),
            "packet_path": str(self.packet_path),
            "cloudflare_ingress_probe_path": str(self.home.cloudflare_ingress_latest_probe),
        }


def _load_json(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    return dict(json.loads(Path(path).read_text(encoding="utf-8")))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="MVP v0.20 release packet and LASTSTANDINGPOINT generator.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="Build and print the current MVP v0.20 packet.")
    status.add_argument("--evidence-json", help="Optional evidence JSON file.")

    render = subparsers.add_parser("render", help="Write LASTSTANDINGPOINT.md from the current packet.")
    render.add_argument("--evidence-json", help="Optional evidence JSON file.")
    render.add_argument("--output", default="LASTSTANDINGPOINT.md", help="Output markdown path.")

    args = parser.parse_args(argv)
    from aether.runtime.body import ConformedRuntimeBody, RuntimeBodyConfig

    body = ConformedRuntimeBody(RuntimeBodyConfig.from_env())
    evidence = _load_json(getattr(args, "evidence_json", None))
    packet = body.mvp20_packet(evidence)

    if args.command == "status":
        print(json.dumps(packet, indent=2, sort_keys=True))
        return

    output = body.mvp20.write_laststandingpoint(Path(args.output), packet=packet)
    print(json.dumps({"ok": True, "output_path": str(output), "packet_id": packet["packet_id"]}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
