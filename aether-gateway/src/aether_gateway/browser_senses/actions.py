"""Receipt-driven projection of governed actions into the Browser Senses UI.

This module does not own action state. It reconstructs a bounded, safe
presentation from the canonical action-path journal and the registered
capability manifest. Approval decisions remain outside Browser Senses.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import hmac
import json
from typing import Any, Mapping, Protocol, Sequence
from urllib.parse import urlencode

from aether.contracts import (
    ActionCapability,
    BrowserSenseCapabilityActionReceipt,
    BrowserSenseCapabilityActionState,
    EventType,
    canonical_action_hash,
    require_browser_sense_action_transition,
)
from aether.contracts.actions import ActionProposal, proposal_from_payload
from aether.events import Event, EventBus


class CapabilityManifestSource(Protocol):
    async def capabilities(self) -> Sequence[ActionCapability]: ...


class ApprovalExpirySource(Protocol):
    def sweep_expired(self) -> list[Any]: ...


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _manifest_payload(capability: ActionCapability) -> dict[str, Any]:
    return {
        "target": capability.target.value,
        "operation": capability.operation,
        "description": capability.description,
        "required_scopes": [scope.value for scope in capability.required_scopes],
        "reversible": capability.reversible,
        "input_schema": dict(capability.input_schema),
        "routing_key": capability.routing_key,
    }


def _manifest_hash(capability: ActionCapability) -> str:
    encoded = json.dumps(
        _manifest_payload(capability),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _governed_route_manifest_hash(proposal: ActionProposal) -> str:
    """Hash the server-routed action boundary when the body capability is hidden.

    Skill and coding bodies are deliberately absent from model-visible
    capabilities. Their action-path proposal still records the governed runtime
    route and selected artifact identifiers. This hash describes that bounded
    server route; it does not claim an external adapter is active.
    """
    metadata = proposal.metadata
    payload = {
        "source": "governed-action-route",
        "target": proposal.target.value,
        "operation": proposal.operation,
        "runtime_id": str(metadata.get("runtime_id") or "default"),
        "skill_id": str(metadata.get("skill_id") or ""),
        "skill_artifact_hash": str(metadata.get("skill_artifact_hash") or ""),
        "coding_task_id": str(metadata.get("coding_task_id") or ""),
        "runtime_candidate_ids": sorted(
            str(item) for item in metadata.get("runtime_candidate_ids") or ()
        ),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _event_type(event: Event) -> str:
    return str(_enum_value(event.event_type))


def _receipt_dict(receipt: BrowserSenseCapabilityActionReceipt) -> dict[str, Any]:
    payload = asdict(receipt)
    payload["state"] = receipt.state.value
    return payload


class BrowserSenseActionProjector:
    """Project action-path evidence without creating a second action ledger."""

    def __init__(
        self,
        event_bus: EventBus,
        capability_source: CapabilityManifestSource,
        approval_expiry_source: ApprovalExpirySource,
    ) -> None:
        self.event_bus = event_bus
        self.capability_source = capability_source
        self.approval_expiry_source = approval_expiry_source

    async def for_correlation(
        self,
        session_id: str,
        correlation_id: str,
    ) -> list[dict[str, Any]]:
        events = self._events()
        action_ids: list[str] = []
        for event in events:
            if _event_type(event) != EventType.ACTION_PROPOSED.value:
                continue
            if str(event.correlation_id or "") != correlation_id:
                continue
            if not self._belongs_to_session(event.payload, session_id):
                continue
            action_id = str(event.payload.get("action_id") or "")
            if action_id and action_id not in action_ids:
                action_ids.append(action_id)
        capabilities = tuple(await self.capability_source.capabilities())
        return [
            self._project(events, capabilities, session_id=session_id, action_id=action_id)
            for action_id in action_ids
        ]

    async def for_action(self, session_id: str, action_id: str) -> dict[str, Any]:
        events = self._events()
        proposed = next(
            (
                event
                for event in events
                if _event_type(event) == EventType.ACTION_PROPOSED.value
                and str(event.payload.get("action_id") or "") == action_id
                and self._belongs_to_session(event.payload, session_id)
            ),
            None,
        )
        if proposed is None:
            raise KeyError(action_id)
        capabilities = tuple(await self.capability_source.capabilities())
        return self._project(
            events,
            capabilities,
            session_id=session_id,
            action_id=action_id,
        )

    def _events(self) -> list[Event]:
        # Expiry is an existing inbox transition. Sweeping it before replay
        # ensures the presentation observes a durable expiry receipt.
        self.approval_expiry_source.sweep_expired()
        return self.event_bus.replay()

    @staticmethod
    def _belongs_to_session(payload: Mapping[str, Any], session_id: str) -> bool:
        metadata = payload.get("metadata")
        if not isinstance(metadata, Mapping):
            return False
        return str(metadata.get("session_id") or "") == f"browser:{session_id}"

    @staticmethod
    def _capability_for(
        proposal: ActionProposal,
        capabilities: Sequence[ActionCapability],
    ) -> ActionCapability | None:
        candidates = [
            capability
            for capability in capabilities
            if capability.target == proposal.target
            and capability.operation == proposal.operation
        ]
        requested_route = str(proposal.metadata.get("runtime_id") or "").strip()
        if requested_route:
            exact = [item for item in candidates if item.routing_key == requested_route]
            if exact:
                candidates = exact
        if not candidates:
            return None
        return sorted(candidates, key=lambda item: str(item.routing_key or ""))[0]

    def _project(
        self,
        events: Sequence[Event],
        capabilities: Sequence[ActionCapability],
        *,
        session_id: str,
        action_id: str,
    ) -> dict[str, Any]:
        action_events = [
            event
            for event in events
            if str(event.payload.get("action_id") or "") == action_id
        ]
        proposed = next(
            (
                event
                for event in action_events
                if _event_type(event) == EventType.ACTION_PROPOSED.value
                and self._belongs_to_session(event.payload, session_id)
            ),
            None,
        )
        if proposed is None:
            raise KeyError(action_id)
        proposal = proposal_from_payload(proposed.payload)
        exact_action_hash = canonical_action_hash(proposal)
        capability = self._capability_for(proposal, capabilities)
        preflight_failed = any(
            _event_type(event) == EventType.ACTION_PREFLIGHT_FAILED.value
            for event in action_events
        )
        adapter_manifest_hash = (
            _manifest_hash(capability)
            if capability is not None
            else _governed_route_manifest_hash(proposal)
        )
        capability_name = f"{proposal.target.value}.{proposal.operation}"
        safe_summary = f"{capability_name} · {proposal.risk.value} risk"
        receipts: list[BrowserSenseCapabilityActionReceipt] = []
        current = BrowserSenseCapabilityActionState.NONE
        approval: dict[str, str] | None = None

        def append_receipt(
            event: Event,
            target: BrowserSenseCapabilityActionState,
            *,
            approval_request_id: str | None = None,
            authoritative: bool = False,
        ) -> None:
            nonlocal current
            if target is current:
                return
            require_browser_sense_action_transition(current, target)
            receipt = BrowserSenseCapabilityActionReceipt(
                receipt_id=event.event_id,
                action_id=action_id,
                session_id=session_id,
                correlation_id=str(proposal.correlation_id or event.correlation_id or ""),
                capability_name=capability_name,
                exact_action_hash=exact_action_hash,
                state=target,
                observed_at=event.timestamp,
                adapter_manifest_hash=(
                    None
                    if target is BrowserSenseCapabilityActionState.UNAVAILABLE
                    and capability is None
                    else adapter_manifest_hash
                ),
                approval_request_id=approval_request_id,
                authoritative_receipt_id=(event.event_id if authoritative else None),
                cancel_supported=False,
                progress=(1.0 if target is BrowserSenseCapabilityActionState.SUCCEEDED else None),
                safe_summary=safe_summary,
                metadata={
                    "source": "action-path-ledger",
                    "event_type": _event_type(event),
                },
            )
            receipts.append(receipt)
            current = target

        for event in action_events:
            kind = _event_type(event)
            if kind == EventType.ACTION_PROPOSED.value:
                if not receipts:
                    append_receipt(event, BrowserSenseCapabilityActionState.PROPOSED)
                continue
            if kind == EventType.APPROVAL_REQUESTED.value:
                event_hash = str(event.payload.get("action_hash") or "")
                if not hmac.compare_digest(event_hash, exact_action_hash):
                    raise ValueError("approval request hash does not match the exact action")
                approval_id = str(event.payload.get("approval_id") or "")
                approval = {
                    "approval_id": approval_id,
                    "expires_at": str(event.payload.get("expires_at") or ""),
                }
                append_receipt(
                    event,
                    BrowserSenseCapabilityActionState.AWAITING_APPROVAL,
                    approval_request_id=approval_id,
                )
                continue
            if kind in {
                EventType.GOVERNANCE_APPROVED.value,
                EventType.APPROVAL_APPROVED.value,
            }:
                append_receipt(event, BrowserSenseCapabilityActionState.QUEUED)
                continue
            if kind == EventType.ACTION_EXECUTION_REQUESTED.value:
                append_receipt(event, BrowserSenseCapabilityActionState.RUNNING)
                continue
            if kind == EventType.ACTION_COMPLETED.value:
                append_receipt(
                    event,
                    BrowserSenseCapabilityActionState.SUCCEEDED,
                    authoritative=True,
                )
                continue
            if kind == EventType.ACTION_FAILED.value:
                append_receipt(
                    event,
                    BrowserSenseCapabilityActionState.FAILED,
                    authoritative=True,
                )
                continue
            if kind == EventType.ACTION_PREFLIGHT_FAILED.value:
                append_receipt(
                    event,
                    BrowserSenseCapabilityActionState.UNAVAILABLE,
                    authoritative=True,
                )
                continue
            if kind in {
                EventType.GOVERNANCE_REJECTED.value,
                EventType.ACTION_RETRY_BLOCKED.value,
                EventType.APPROVAL_REJECTED.value,
                EventType.APPROVAL_EXPIRED.value,
            }:
                append_receipt(
                    event,
                    BrowserSenseCapabilityActionState.REJECTED,
                    authoritative=True,
                )

        if not receipts:
            raise RuntimeError("action journal contains no presentable authoritative receipt")
        current_receipt = receipts[-1]
        handoff: dict[str, Any] | None = None
        if (
            current_receipt.state is BrowserSenseCapabilityActionState.AWAITING_APPROVAL
            and approval is not None
        ):
            route_query = urlencode({
                "approval_id": approval["approval_id"],
                "action_hash": exact_action_hash,
            })
            handoff = {
                "approval_id": approval["approval_id"],
                "exact_action_hash": exact_action_hash,
                "expires_at": approval["expires_at"],
                "decision_in_senses": False,
                "aionui_route": f"/#/approvals?{route_query}",
                "telegram_command": "/approvals",
            }
        return {
            "action_id": action_id,
            "receipts": [_receipt_dict(receipt) for receipt in receipts],
            "current": _receipt_dict(current_receipt),
            "approval_handoff": handoff,
        }
