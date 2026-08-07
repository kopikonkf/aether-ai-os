from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import struct
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


class _Raises:
    def __init__(self, exception_type, match: str) -> None:
        self.exception_type = exception_type
        self.match = match

    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception, traceback) -> bool:
        if exception_type is None:
            raise AssertionError(f"expected {self.exception_type.__name__}")
        if not issubclass(exception_type, self.exception_type):
            return False
        if self.match not in str(exception):
            raise AssertionError(
                f"expected {self.match!r} in exception, got {str(exception)!r}"
            )
        return True


class _PytestCompat:
    @staticmethod
    def raises(exception_type, *, match: str):
        return _Raises(exception_type, match)


pytest = _PytestCompat()


MODULE_PATH = (
    Path(__file__).parents[1]
    / "src"
    / "aether_gateway"
    / "browser_senses"
    / "vision.py"
)
SPEC = importlib.util.spec_from_file_location("aether_vision_lifecycle", MODULE_PATH)
assert SPEC and SPEC.loader
vision = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(vision)


def png(width: int = 2, height: int = 3) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(
        ">II", width, height
    ) + b"\x08\x02\x00\x00\x00" + b"bounded-pixels"


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 8, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


def lifecycle(tmp_path: Path, clock: Clock):
    return vision.VisionLifecycle(
        tmp_path / "vision.sqlite3",
        tmp_path / "frames",
        maximum_frame_bytes=1024,
        now=clock,
    )


def grant(manager, *, source="camera", mode="bounded", device_id="device.1"):
    capability = "camera" if source == "camera" else "screen-share"
    return manager.grant_consent(
        session_id="session.1",
        device_id=device_id,
        source=source,
        mode=mode,
        capabilities=(capability,),
    )


def accept(manager, consent, clock, *, sequence=1, source="camera", raw=None):
    return manager.accept_frame(
        session_id="session.1",
        device_id="device.1",
        consent_id=consent["consent_id"],
        source=source,
        sequence_number=sequence,
        captured_at=clock().isoformat().replace("+00:00", "Z"),
        content_type="image/png",
        raw=raw or png(),
        declared_width=2,
        declared_height=3,
        prompt="Describe only what is materially visible.",
        turn_id=f"turn.{sequence}",
        correlation_id=f"corr.{sequence}",
    )


def test_bounded_lease_is_server_timed_device_bound_and_sequence_monotonic(
    tmp_path: Path,
) -> None:
    clock = Clock()
    manager = lifecycle(tmp_path, clock)
    consent = grant(manager)

    assert consent["source"] == "camera"
    assert consent["mode"] == "bounded"
    assert consent["capture_interval_seconds"] == 15
    assert consent["expires_at"] == "2026-08-08T00:15:00Z"
    assert consent["receipt_id"].startswith("vision-consent-event.")
    assert "device_id" not in consent

    first = accept(manager, consent, clock)
    assert first["sequence_number"] == 1
    assert first["content_hash"]
    assert first["ephemeral_handle"].startswith("vision-frame.")
    public_first = {key: value for key, value in first.items() if key != "_working_path"}
    assert "raw" not in public_first
    assert "data_base64" not in public_first
    assert "prompt" not in public_first
    assert Path(first["_working_path"]).exists()
    assert oct(Path(first["_working_path"]).stat().st_mode & 0o777) == "0o600"

    clock.advance(14)
    with pytest.raises(vision.VisionConsentError, match="15-second"):
        accept(manager, consent, clock, sequence=2)
    clock.advance(1)
    second = accept(manager, consent, clock, sequence=2)
    assert second["sequence_number"] == 2

    with pytest.raises(vision.VisionConsentError, match="device binding"):
        manager.accept_frame(
            session_id="session.1",
            device_id="device.other",
            consent_id=consent["consent_id"],
            source="camera",
            sequence_number=3,
            captured_at=clock().isoformat().replace("+00:00", "Z"),
            content_type="image/png",
            raw=png(),
            declared_width=2,
            declared_height=3,
            prompt="visible",
            turn_id="turn.wrong-device",
            correlation_id="corr.wrong-device",
        )


def test_one_shot_is_consumed_once_and_camera_never_authorizes_screen(
    tmp_path: Path,
) -> None:
    clock = Clock()
    manager = lifecycle(tmp_path, clock)
    one_shot = grant(manager, mode="one-shot")
    accepted = accept(manager, one_shot, clock)
    manager.delete_frame(accepted["frame_id"], reason="turn-terminal")

    assert manager.frame_receipt(accepted["frame_id"])["deletion_outcome"] == "deleted"
    assert not Path(accepted["_working_path"]).exists()
    with pytest.raises(vision.VisionConsentError, match="revoked"):
        accept(manager, one_shot, clock)
    with pytest.raises(vision.VisionConsentError, match="source binding"):
        accept(manager, grant(manager), clock, source="screen")


def test_content_is_signature_and_dimension_validated_before_persistence(
    tmp_path: Path,
) -> None:
    clock = Clock()
    manager = lifecycle(tmp_path, clock)
    consent = grant(manager, mode="one-shot")

    with pytest.raises(vision.VisionFrameValidationError, match="signature"):
        accept(manager, consent, clock, raw=b"not-a-real-png")
    with pytest.raises(vision.VisionFrameValidationError, match="dimensions"):
        manager.accept_frame(
            session_id="session.1",
            device_id="device.1",
            consent_id=consent["consent_id"],
            source="camera",
            sequence_number=1,
            captured_at="2026-08-08T00:00:00Z",
            content_type="image/png",
            raw=png(2, 3),
            declared_width=9,
            declared_height=9,
            prompt="visible",
            turn_id="turn.bad-dimensions",
            correlation_id="corr.bad-dimensions",
        )
    assert list((tmp_path / "frames").glob("*")) == []


def test_expiry_revocation_and_session_close_fail_closed(tmp_path: Path) -> None:
    clock = Clock()
    manager = lifecycle(tmp_path, clock)
    consent = grant(manager)
    revoked = manager.revoke_consent(
        session_id="session.1",
        device_id="device.1",
        consent_id=consent["consent_id"],
        reason="camera-stop",
    )
    assert revoked["state"] == "revoked"
    assert revoked["receipt_id"].startswith("vision-consent-event.")
    with pytest.raises(vision.VisionConsentError, match="revoked"):
        accept(manager, consent, clock)

    expiring = grant(manager)
    clock.advance(901)
    with pytest.raises(vision.VisionConsentError, match="expired"):
        accept(manager, expiring, clock)

    camera = grant(manager)
    screen = grant(manager, source="screen")
    receipts = manager.revoke_session("session.1", reason="session-closed")
    assert {item["consent_id"] for item in receipts} == {
        camera["consent_id"],
        screen["consent_id"],
    }


def test_terminal_turn_deletes_raw_and_crash_sweeper_receipts_orphans(
    tmp_path: Path,
) -> None:
    clock = Clock()
    manager = lifecycle(tmp_path, clock)
    consent = grant(manager)
    staged = accept(manager, consent, clock)
    raw_path = Path(staged["_working_path"])

    old = clock().timestamp() - 301
    os.utime(raw_path, (old, old))
    swept = manager.sweep_orphans(maximum_age_seconds=300)
    assert swept == 1
    assert not raw_path.exists()
    receipt = manager.frame_receipt(staged["frame_id"])
    assert receipt["deletion_outcome"] == "swept"
    assert receipt["deleted_at"] == "2026-08-08T00:00:00Z"
    assert "_working_path" not in receipt

    for database_path in tmp_path.glob("vision.sqlite3*"):
        contents = database_path.read_bytes()
        assert png() not in contents
        assert b"Describe only what is materially visible" not in contents
    with sqlite3.connect(tmp_path / "vision.sqlite3") as conn:
        payloads = "\n".join(
            row[0]
            for row in conn.execute("SELECT payload_json FROM vision_frame_events")
        )
    assert "bounded-pixels" not in payloads
    assert str(tmp_path) not in payloads


if __name__ == "__main__":
    tests = (
        test_bounded_lease_is_server_timed_device_bound_and_sequence_monotonic,
        test_one_shot_is_consumed_once_and_camera_never_authorizes_screen,
        test_content_is_signature_and_dimension_validated_before_persistence,
        test_expiry_revocation_and_session_close_fail_closed,
        test_terminal_turn_deletes_raw_and_crash_sweeper_receipts_orphans,
    )
    for test_case in tests:
        with tempfile.TemporaryDirectory() as directory:
            test_case(Path(directory))
    print(f"{len(tests)} vision lifecycle tests passed")
