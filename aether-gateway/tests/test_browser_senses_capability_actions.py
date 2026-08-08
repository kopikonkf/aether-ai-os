from __future__ import annotations

import asyncio
import json
import pytest

from aether.contracts import (
    ActionCapability,
    ActionRisk,
    ActionScope,
    ActionTarget,
    EventType,
)
from aether.events import Event
from aether.contracts.actions import canonical_action_hash, proposal_from_payload
from aether_gateway.browser_senses.actions import BrowserSenseActionProjector


SESSION_ID = "sense-session.browser-a"
CORRELATION_ID = "corr.browser-a"
ACTION_ID = "act.browser-a"


class FakeEventBus:
    def __init__(self, events: list[Event]) -> None:
        self.events = events

    def replay(self) -> list[Event]:
        return list(self.events)


class FakeCapabilities:
    async def capabilities(self) -> list[ActionCapability]:
        return [
            ActionCapability(
                target=ActionTarget.TOOL,
                operation="write",
                description="Write through the existing governed tool adapter",
                required_scopes=(ActionScope.WRITE,),
                reversible=True,
                input_schema={"type": "object"},
                cancel_supported=True,
            )
        ]


class FakeApprovalInbox:
    def sweep_expired(self) -> list[object]:
        return []


def _event(event_type: EventType, payload: dict, *, sequence: int) -> Event:
    return Event(
        event_type=event_type,
        actor="test",
        payload=payload,
        event_id=f"evt.{sequence}",
        timestamp=f"2026-08-08T00:00:0{sequence}Z",
        correlation_id=CORRELATION_ID,
    )


def _proposal_payload(*, session_id: str = SESSION_ID) -> dict:
    return {
        "action_id": ACTION_ID,
        "target": "tool",
        "operation": "write",
        "arguments": {
            "path": "workspace/proof.md",
            "secret": "must-never-reach-senses",
        },
        "required_scopes": ["write"],
        "reason": "Create the requested proof artifact",
        "risk": ActionRisk.MEDIUM.value,
        "reversible": True,
        "correlation_id": CORRELATION_ID,
        "retry_reason": None,
        "metadata": {
            "channel": "browser",
            "session_id": f"browser:{session_id}",
        },
    }


def _action_hash(session_id: str = SESSION_ID) -> str:
    return canonical_action_hash(proposal_from_payload(_proposal_payload(session_id=session_id)))


def _project(events: list[Event], *, session_id: str = SESSION_ID) -> list[dict]:
    projector = BrowserSenseActionProjector(
        FakeEventBus(events),
        FakeCapabilities(),
        FakeApprovalInbox(),
    )
    return asyncio.run(projector.for_correlation(session_id, CORRELATION_ID))


def test_pending_action_projects_ordered_receipts_and_trusted_handoff_only() -> None:
    events = [
        _event(EventType.ACTION_PROPOSED, _proposal_payload(), sequence=1),
        _event(
            EventType.GOVERNANCE_APPROVAL_REQUIRED,
            {"action_id": ACTION_ID, "decision_id": "decision.1"},
            sequence=2,
        ),
        _event(
            EventType.APPROVAL_REQUESTED,
            {
                "approval_id": "approval.browser-a",
                "action_id": ACTION_ID,
                "action_hash": _action_hash(),
                "expires_at": "2026-08-08T00:15:00Z",
                "request_channel": "browser",
            },
            sequence=3,
        ),
    ]

    projected = _project(events)

    assert len(projected) == 1
    action = projected[0]
    assert [receipt["state"] for receipt in action["receipts"]] == [
        "proposed",
        "awaiting-approval",
    ]
    assert action["current"]["approval_request_id"] == "approval.browser-a"
    assert action["approval_handoff"] == {
        "approval_id": "approval.browser-a",
        "exact_action_hash": action["current"]["exact_action_hash"],
        "expires_at": "2026-08-08T00:15:00Z",
        "decision_in_senses": False,
        "aionui_route": (
            "/#/approvals?approval_id=approval.browser-a&action_hash="
            f"{action['current']['exact_action_hash']}"
        ),
        "telegram_command": "/approvals",
    }
    encoded = json.dumps(action, sort_keys=True)
    assert "must-never-reach-senses" not in encoded
    assert "workspace/proof.md" not in encoded
    assert '"arguments"' not in encoded
    assert '"output"' not in encoded


def test_projector_binds_action_to_exact_browser_session() -> None:
    events = [_event(EventType.ACTION_PROPOSED, _proposal_payload(), sequence=1)]

    assert _project(events, session_id="sense-session.other") == []

    projector = BrowserSenseActionProjector(
        FakeEventBus(events),
        FakeCapabilities(),
        FakeApprovalInbox(),
    )
    with pytest.raises(KeyError):
        asyncio.run(projector.for_action("sense-session.other", ACTION_ID))


@pytest.mark.parametrize(
    ("terminal_event", "expected_state"),
    [
        (EventType.ACTION_COMPLETED, "succeeded"),
        (EventType.ACTION_FAILED, "failed"),
        (EventType.APPROVAL_REJECTED, "rejected"),
        (EventType.ACTION_PREFLIGHT_FAILED, "unavailable"),
    ],
)
def test_terminal_projection_is_bound_to_authoritative_ledger_receipt(
    terminal_event: EventType,
    expected_state: str,
) -> None:
    events = [_event(EventType.ACTION_PROPOSED, _proposal_payload(), sequence=1)]
    if terminal_event in {EventType.ACTION_COMPLETED, EventType.ACTION_FAILED}:
        events.extend(
            [
                _event(
                    EventType.GOVERNANCE_APPROVED,
                    {"action_id": ACTION_ID},
                    sequence=2,
                ),
                _event(
                    EventType.ACTION_EXECUTION_REQUESTED,
                    {"action_id": ACTION_ID},
                    sequence=3,
                ),
            ]
        )
        terminal_sequence = 4
    elif terminal_event is EventType.APPROVAL_REJECTED:
        events.append(
            _event(
                EventType.APPROVAL_REQUESTED,
                {
                    "approval_id": "approval.browser-a",
                    "action_id": ACTION_ID,
                    "action_hash": _action_hash(),
                    "expires_at": "2026-08-08T00:15:00Z",
                    "request_channel": "browser",
                },
                sequence=2,
            )
        )
        terminal_sequence = 3
    else:
        terminal_sequence = 2
    events.append(
        _event(
            terminal_event,
            {
                "action_id": ACTION_ID,
                "output": {"secret": "terminal-output-must-stay-server-side"},
                "error": "bounded test failure",
            },
            sequence=terminal_sequence,
        )
    )

    projected = _project(events)[0]

    assert projected["current"]["state"] == expected_state
    assert projected["current"]["authoritative_receipt_id"] == f"evt.{terminal_sequence}"
    assert "terminal-output-must-stay-server-side" not in json.dumps(projected)


def test_registered_capability_manifest_hash_is_server_derived() -> None:
    projected = _project(
        [_event(EventType.ACTION_PROPOSED, _proposal_payload(), sequence=1)]
    )[0]

    assert len(projected["current"]["adapter_manifest_hash"]) == 64
    assert projected["current"]["capability_name"] == "tool.write"
    assert projected["current"]["safe_summary"] == "tool.write · medium risk"
    assert projected["current"]["cancel_supported"] is True


def _running_events() -> list[Event]:
    return [
        _event(EventType.ACTION_PROPOSED, _proposal_payload(), sequence=1),
        _event(EventType.GOVERNANCE_APPROVED, {"action_id": ACTION_ID}, sequence=2),
        _event(EventType.ACTION_EXECUTION_REQUESTED, {"action_id": ACTION_ID}, sequence=3),
    ]


def test_supported_cancellation_projects_exact_control_receipts_and_ignores_late_result() -> None:
    events = _running_events() + [
        _event(
            EventType.ACTION_CANCEL_INTENT_RECORDED,
            {
                "action_id": ACTION_ID,
                "action_hash": _action_hash(),
                "control_request_id": "cancel.1",
                "session_id": SESSION_ID,
            },
            sequence=4,
        ),
        _event(
            EventType.ACTION_CANCEL_REQUESTED,
            {
                "action_id": ACTION_ID,
                "action_hash": _action_hash(),
                "control_request_id": "cancel.1",
            },
            sequence=5,
        ),
        _event(
            EventType.ACTION_CANCELED,
            {
                "action_id": ACTION_ID,
                "action_hash": _action_hash(),
                "control_request_id": "cancel.1",
            },
            sequence=6,
        ),
        _event(
            EventType.ACTION_LATE_RESULT_DISCARDED,
            {
                "action_id": ACTION_ID,
                "result_hash": "f" * 64,
            },
            sequence=7,
        ),
    ]

    projected = _project(events)[0]

    assert [item["state"] for item in projected["receipts"]] == [
        "proposed", "queued", "running", "running", "canceling", "canceled",
    ]
    assert projected["current"]["state"] == "canceled"
    assert projected["current"]["control_request_id"] == "cancel.1"
    assert projected["current"]["cancellation_status"] == "confirmed"
    assert projected["current"]["authoritative_receipt_id"] == "evt.6"
    assert "result_hash" not in json.dumps(projected)


def test_network_ambiguity_stays_not_confirmed_until_late_terminal_receipt() -> None:
    ambiguous = _running_events() + [
        _event(
            EventType.ACTION_RECONCILIATION_REQUESTED,
            {
                "action_id": ACTION_ID,
                "action_hash": _action_hash(),
                "control_request_id": "reconcile.1",
                "observed_receipt_id": "evt.3",
                "outcome": "not-confirmed",
            },
            sequence=4,
        ),
    ]

    projected = _project(ambiguous)[0]
    assert projected["current"]["state"] == "reconciling"
    assert projected["current"]["reconciliation_status"] == "not-confirmed"
    assert projected["current"]["authoritative_receipt_id"] is None

    reconciled = _project(ambiguous + [
        _event(
            EventType.ACTION_COMPLETED,
            {"action_id": ACTION_ID, "output": "must-remain-server-side"},
            sequence=5,
        )
    ])[0]
    assert reconciled["current"]["state"] == "succeeded"
    assert reconciled["current"]["reconciliation_status"] == "confirmed"
    assert reconciled["current"]["authoritative_receipt_id"] == "evt.5"
    assert "must-remain-server-side" not in json.dumps(reconciled)


def test_unsupported_cancel_receipt_never_claims_terminal_cancellation() -> None:
    events = _running_events() + [
        _event(
            EventType.ACTION_CANCEL_INTENT_RECORDED,
            {
                "action_id": ACTION_ID,
                "action_hash": _action_hash(),
                "control_request_id": "cancel.unsupported",
                "session_id": SESSION_ID,
            },
            sequence=4,
        ),
        _event(
            EventType.ACTION_CANCEL_UNSUPPORTED,
            {
                "action_id": ACTION_ID,
                "action_hash": _action_hash(),
                "control_request_id": "cancel.unsupported",
            },
            sequence=5,
        ),
    ]

    projected = _project(events)[0]

    assert projected["current"]["state"] == "running"
    assert projected["current"]["cancellation_status"] == "unsupported"
    assert projected["current"]["authoritative_receipt_id"] == "evt.5"
