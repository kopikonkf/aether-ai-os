from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aether_gateway.browser_senses import (
    LiveKitGrantError,
    LiveKitGrantLedger,
    LiveKitRevokePort,
)


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 9, 0, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value = self.value + timedelta(seconds=seconds)


def test_grant_records_issue_and_exposes_bounded_public_state(tmp_path: Path) -> None:
    ledger = LiveKitGrantLedger(tmp_path / "grants.sqlite3")
    grant = ledger.record_grant(
        session_id="sense-session.1",
        room_name="aether-sense-session.1",
        participant_identity="founder-1",
        participant_token="jwt-token-abc",
    )

    assert grant["grant_id"].startswith("livekit-grant.")
    assert grant["session_id"] == "sense-session.1"
    assert grant["room_name"] == "aether-sense-session.1"
    assert grant["participant_identity"] == "founder-1"
    assert grant["state"] == "issued"
    assert grant["reason"] == "session-issued"
    assert "token" not in str(grant).casefold()
    assert "jwt-token-abc" not in str(grant)

    status = ledger.status()
    assert status["grants"] == 1
    assert status["grant_events"] == 1


def test_grant_is_append_only(tmp_path: Path) -> None:
    ledger = LiveKitGrantLedger(tmp_path / "grants.sqlite3")
    grant = ledger.record_grant(
        session_id="sense-session.1",
        room_name="aether-room-1",
        participant_identity="founder-1",
        participant_token="token-x",
    )

    with sqlite3.connect(ledger.path) as conn:
        try:
            conn.execute(
                "UPDATE livekit_grants SET room_name='tampered' WHERE grant_id=?",
                (grant["grant_id"],),
            )
        except sqlite3.DatabaseError as exc:
            assert "append-only" in str(exc)
        else:
            raise AssertionError("LiveKit grant evidence must be append-only")


def test_session_close_revokes_all_grants(tmp_path: Path) -> None:
    ledger = LiveKitGrantLedger(tmp_path / "grants.sqlite3")
    for index in range(2):
        ledger.record_grant(
            session_id="sense-session.1",
            room_name=f"aether-room-{index}",
            participant_identity=f"founder-{index}",
            participant_token=f"token-{index}",
        )

    revoked = ledger.revoke_for_session("sense-session.1", reason="device-revoked")
    assert len(revoked) == 2
    assert all(item["state"] == "revoked" for item in revoked)
    assert all(item["reason"] == "device-revoked" for item in revoked)
    assert ledger.active_for_session("sense-session.1") == []
    assert ledger.status()["grant_events"] == 4


def test_revoked_grant_is_not_usable_and_revoke_is_idempotent(tmp_path: Path) -> None:
    ledger = LiveKitGrantLedger(tmp_path / "grants.sqlite3")
    grant = ledger.record_grant(
        session_id="sense-session.1",
        room_name="aether-room-1",
        participant_identity="founder-1",
        participant_token="token-x",
    )

    ledger.assert_usable(grant["grant_id"])
    ledger.revoke_for_session("sense-session.1", reason="session-closed")
    try:
        ledger.assert_usable(grant["grant_id"])
    except LiveKitGrantError as exc:
        assert "revoked" in str(exc)
    else:
        raise AssertionError("revoked grant must not be usable")

    again = ledger.revoke_for_session("sense-session.1", reason="session-closed")
    assert again == []
    assert ledger.grant_state(grant["grant_id"])["state"] == "revoked"


def test_grant_expires_after_ttl(tmp_path: Path) -> None:
    clock = Clock()
    ledger = LiveKitGrantLedger(tmp_path / "grants.sqlite3", now=clock)
    grant = ledger.record_grant(
        session_id="sense-session.1",
        room_name="aether-room-1",
        participant_identity="founder-1",
        participant_token="token-x",
        expires_at="2026-08-09T01:00:00Z",
    )

    assert ledger.grant_state(grant["grant_id"])["state"] == "issued"
    clock.advance(3600 + 1)
    state = ledger.grant_state(grant["grant_id"])
    assert state["state"] == "expired"
    assert state["reason"] == "ttl-expired"
    assert ledger.active_for_session("sense-session.1") == []
    try:
        ledger.assert_usable(grant["grant_id"])
    except LiveKitGrantError as exc:
        assert "expired" in str(exc)
    else:
        raise AssertionError("expired grant must not be usable")


def test_unknown_grant_raises(tmp_path: Path) -> None:
    ledger = LiveKitGrantLedger(tmp_path / "grants.sqlite3")
    try:
        ledger.grant_state("livekit-grant.missing")
    except LiveKitGrantError as exc:
        assert "unknown" in str(exc)
    else:
        raise AssertionError("unknown grant must raise")


class FakeRevokePort:
    def __init__(self, outcome: dict) -> None:
        self.outcome = outcome
        self.calls = []

    def revoke(self, *, room_name, participant_identity, reason):
        self.calls.append((room_name, participant_identity, reason))
        return self.outcome


def test_revoke_records_honest_livekit_side_and_never_returns_token(tmp_path: Path) -> None:
    ledger = LiveKitGrantLedger(tmp_path / "grants.sqlite3")
    grant = ledger.record_grant(
        session_id="sense-session.1",
        room_name="aether-room-1",
        participant_identity="founder-1",
        participant_token="jwt-secret-token",
    )
    port = FakeRevokePort({"livekit_side": "revoked", "confirmed": True, "reason": "x"})
    revoked = ledger.revoke_for_session("sense-session.1", reason="device-revoked", revoke_port=port)

    assert revoked[0]["livekit_side"]["livekit_side"] == "revoked"
    assert port.calls == [("aether-room-1", "founder-1", "device-revoked")]
    # The grant API view must never leak the raw bearer token.
    assert "jwt-secret-token" not in str(revoked)


def test_revoke_port_is_honest_when_livekit_not_wired(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("LIVEKIT_URL", raising=False)
    monkeypatch.delenv("LIVEKIT_API_KEY", raising=False)
    monkeypatch.delenv("LIVEKIT_API_SECRET", raising=False)
    port = LiveKitRevokePort()
    assert port.status()["livekit_side"] == "not-wired"
    outcome = port.revoke(room_name="room", participant_identity="founder", reason="r")
    assert outcome["livekit_side"] == "not-wired"
    assert outcome["confirmed"] is False
    assert "local authorization-ledger" in outcome["reason"]


def test_revoke_port_reports_failure_without_confirming(tmp_path: Path, monkeypatch) -> None:
    """A provider-revoke failure/timeout must never yield confirmed=true."""

    def broken_sdk():
        class FakeApi:
            class RoomServiceClient:
                def __init__(self, url, api_key, api_secret):
                    pass

                @staticmethod
                def remove_participant(room, identity):
                    raise RuntimeError("simulated provider timeout")

        return FakeApi

    port = LiveKitRevokePort(
        url="wss://livekit.invalid",
        api_key="key",
        api_secret="secret" * 8,
        sdk_loader=broken_sdk,
    )
    assert port.status()["livekit_side"] == "wired"
    outcome = port.revoke(room_name="room", participant_identity="founder", reason="r")

    assert outcome["livekit_side"] == "revoke-failed"
    assert outcome["confirmed"] is False
    assert "simulated provider timeout" in outcome["reason"]

    # The ledger records the failure honestly: grant is revoked locally,
    # but confirmed stays False because LiveKit-side disconnect was not proven.
    ledger = LiveKitGrantLedger(tmp_path / "grants.sqlite3")
    ledger.record_grant(
        session_id="sense-session.1",
        room_name="room",
        participant_identity="founder-1",
        participant_token="token-x",
    )
    revoked = ledger.revoke_for_session(
        "sense-session.1", reason="device-revoked", revoke_port=port
    )
    assert revoked[0]["state"] == "revoked"
    assert revoked[0]["livekit_side"]["confirmed"] is False
    assert revoked[0]["livekit_side"]["livekit_side"] == "revoke-failed"


def test_revoke_port_confirmed_only_on_success(tmp_path: Path) -> None:
    def good_sdk():
        class FakeApi:
            class RoomServiceClient:
                def __init__(self, url, api_key, api_secret):
                    self.calls = []

                def remove_participant(self, room, identity):
                    self.calls.append((room, identity))

        return FakeApi

    port = LiveKitRevokePort(
        url="wss://livekit.invalid",
        api_key="key",
        api_secret="secret" * 8,
        sdk_loader=good_sdk,
    )
    outcome = port.revoke(room_name="room", participant_identity="founder", reason="r")
    assert outcome["livekit_side"] == "revoked"
    assert outcome["confirmed"] is True
