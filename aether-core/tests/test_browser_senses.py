from __future__ import annotations

import sqlite3
from pathlib import Path

from aether.browser_senses import BrowserSenseStore
from aether.contracts import (
    BrowserSenseCapability,
    BrowserSenseCapabilityActionReceipt,
    BrowserSenseCapabilityActionState,
    BrowserSenseConsentMode,
    BrowserSenseConsentRecord,
    BrowserSenseConsentSource,
    BrowserSenseConsentState,
    BrowserSenseInterruptionReason,
    BrowserSenseInterruptionReceipt,
    BrowserSenseRuntimeProfile,
    BrowserSenseSession,
    BrowserSenseSessionState,
    BrowserSenseTransport,
    browser_sense_session_payload,
    require_browser_sense_action_transition,
    require_browser_sense_v1_runtime_profile,
)


def _session() -> BrowserSenseSession:
    return BrowserSenseSession(
        session_id="sense-session.1",
        room_name="aether-room-1",
        participant_identity="founder-1",
        capabilities=(BrowserSenseCapability.TEXT, BrowserSenseCapability.MICROPHONE),
        transports=(BrowserSenseTransport.LIVEKIT, BrowserSenseTransport.HTTP_KEYFRAME),
        state=BrowserSenseSessionState.ISSUED,
        issued_at="2026-07-28T00:00:00Z",
        expires_at="2026-07-28T01:00:00Z",
        token_hash="a" * 64,
        principal="founder",
        runtime_profile=BrowserSenseRuntimeProfile.GOVERNED_PIPELINE,
    )


def test_browser_sense_session_hash_and_append_only_store(tmp_path: Path) -> None:
    store = BrowserSenseStore(tmp_path / "senses.sqlite3")
    session = store.record_session(_session())
    active = store.transition_session(session.session_id, BrowserSenseSessionState.ACTIVE, recorded_at="2026-07-28T00:00:05Z")

    assert active.state is BrowserSenseSessionState.ACTIVE
    assert active.runtime_profile is BrowserSenseRuntimeProfile.GOVERNED_PIPELINE
    assert store.get_session(session.session_id).state is BrowserSenseSessionState.ACTIVE
    assert store.get_session_by_room(session.room_name).session_id == session.session_id
    assert store.status()["session_events"] == 2

    with sqlite3.connect(store.path) as conn:
        try:
            conn.execute("UPDATE browser_sense_sessions SET state='closed'")
        except sqlite3.DatabaseError as exc:
            assert "append-only" in str(exc)
        else:
            raise AssertionError("browser sense evidence must be append-only")


def test_legacy_session_payload_remains_readable_without_runtime_profile(tmp_path: Path) -> None:
    legacy = BrowserSenseSession(
        session_id="sense-session.legacy",
        room_name="aether-room-legacy",
        participant_identity="founder-legacy",
        capabilities=(BrowserSenseCapability.TEXT,),
        transports=(BrowserSenseTransport.WEBSOCKET_TEXT,),
        state=BrowserSenseSessionState.ISSUED,
        issued_at="2026-07-28T00:00:00Z",
        expires_at="2026-07-28T01:00:00Z",
        token_hash="c" * 64,
        principal="founder",
    )
    assert "runtime_profile" not in browser_sense_session_payload(legacy)

    store = BrowserSenseStore(tmp_path / "legacy-senses.sqlite3")
    store.record_session(legacy)
    restored = store.get_session(legacy.session_id)
    assert restored.runtime_profile is None
    assert restored.fingerprint == legacy.fingerprint


def test_v1_runtime_profile_guard_rejects_legacy_and_native_audio() -> None:
    assert require_browser_sense_v1_runtime_profile(
        BrowserSenseRuntimeProfile.GOVERNED_PIPELINE
    ) is BrowserSenseRuntimeProfile.GOVERNED_PIPELINE

    for rejected in (None, BrowserSenseRuntimeProfile.NATIVE_AUDIO_EXPERIMENTAL):
        try:
            require_browser_sense_v1_runtime_profile(rejected)
        except ValueError as exc:
            assert "GOVERNED_PIPELINE" in str(exc)
        else:
            raise AssertionError("non-governed runtime profile must not enter v1")


def test_bounded_consent_requires_fixed_interval_and_expiry() -> None:
    consent = BrowserSenseConsentRecord(
        consent_id="sense-consent.1",
        session_id="sense-session.1",
        source="camera",
        mode="bounded",
        state="granted",
        granted_at="2026-08-07T00:00:00Z",
        recorded_at="2026-08-07T00:00:00Z",
        expires_at="2026-08-07T00:15:00Z",
        capture_interval_seconds=15,
        sequence_number=0,
    )
    assert consent.source is BrowserSenseConsentSource.CAMERA
    assert consent.mode is BrowserSenseConsentMode.BOUNDED
    assert consent.state is BrowserSenseConsentState.GRANTED
    assert consent.capture_interval_seconds == 15

    try:
        BrowserSenseConsentRecord(
            consent_id="sense-consent.2",
            session_id="sense-session.1",
            source=BrowserSenseConsentSource.SCREEN,
            mode=BrowserSenseConsentMode.BOUNDED,
            state=BrowserSenseConsentState.GRANTED,
            granted_at="2026-08-07T00:00:00Z",
            recorded_at="2026-08-07T00:00:00Z",
            capture_interval_seconds=10,
        )
    except ValueError as exc:
        assert "15-second" in str(exc)
    else:
        raise AssertionError("bounded consent must enforce the frozen interval")


def test_interruption_receipt_requires_new_generation_and_truthful_cancel() -> None:
    receipt = BrowserSenseInterruptionReceipt(
        receipt_id="sense-interruption.1",
        session_id="sense-session.1",
        turn_id="sense-turn.1",
        reason="user_barge_in",
        requested_at="2026-08-07T00:00:01Z",
        audio_silent_at="2026-08-07T00:00:01.150Z",
        previous_generation=4,
        next_generation=5,
        delivered_audio_ms=820,
        provider_cancel_supported=True,
        provider_cancelled=True,
    )
    assert receipt.reason is BrowserSenseInterruptionReason.USER_BARGE_IN
    assert receipt.next_generation == 5

    try:
        BrowserSenseInterruptionReceipt(
            receipt_id="sense-interruption.2",
            session_id="sense-session.1",
            turn_id="sense-turn.1",
            reason=BrowserSenseInterruptionReason.EXPLICIT_STOP,
            requested_at="2026-08-07T00:00:01Z",
            audio_silent_at="2026-08-07T00:00:01.100Z",
            previous_generation=4,
            next_generation=4,
            provider_cancel_supported=False,
            provider_cancelled=True,
        )
    except ValueError as exc:
        assert "generation" in str(exc)
    else:
        raise AssertionError("interruption must invalidate the prior generation")

    try:
        BrowserSenseInterruptionReceipt(
            receipt_id="sense-interruption.3",
            session_id="sense-session.1",
            turn_id="sense-turn.1",
            reason=BrowserSenseInterruptionReason.EXPLICIT_STOP,
            requested_at="2026-08-07T00:00:01Z",
            audio_silent_at="2026-08-07T00:00:01.100Z",
            previous_generation=4,
            next_generation=5,
            provider_cancel_supported=False,
            provider_cancelled=True,
        )
    except ValueError as exc:
        assert "cancellation" in str(exc)
    else:
        raise AssertionError("provider cancellation must be reported truthfully")


def test_capability_action_terminal_success_requires_authoritative_receipt() -> None:
    assert require_browser_sense_action_transition(
        BrowserSenseCapabilityActionState.NONE,
        BrowserSenseCapabilityActionState.PROPOSED,
    ) is BrowserSenseCapabilityActionState.PROPOSED
    assert require_browser_sense_action_transition(
        BrowserSenseCapabilityActionState.RUNNING,
        BrowserSenseCapabilityActionState.RECONCILING,
    ) is BrowserSenseCapabilityActionState.RECONCILING

    try:
        require_browser_sense_action_transition(
            BrowserSenseCapabilityActionState.PROPOSED,
            BrowserSenseCapabilityActionState.SUCCEEDED,
        )
    except ValueError as exc:
        assert "invalid browser sense capability action transition" in str(exc)
    else:
        raise AssertionError("narration must not jump a proposal to success")

    common = {
        "receipt_id": "sense-action-state.1",
        "action_id": "action.1",
        "session_id": "sense-session.1",
        "correlation_id": "corr.1",
        "capability_name": "browser.observe",
        "exact_action_hash": "a" * 64,
        "adapter_manifest_hash": "b" * 64,
        "state": "succeeded",
        "observed_at": "2026-08-07T00:00:02Z",
    }
    try:
        BrowserSenseCapabilityActionReceipt(**common)
    except ValueError as exc:
        assert "authoritative receipt" in str(exc)
    else:
        raise AssertionError("success narration is not execution evidence")

    succeeded = BrowserSenseCapabilityActionReceipt(
        **common,
        authoritative_receipt_id="execution-receipt.1",
    )
    assert succeeded.state is BrowserSenseCapabilityActionState.SUCCEEDED
