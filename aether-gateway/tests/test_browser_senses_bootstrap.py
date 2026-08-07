from __future__ import annotations

import base64
import hashlib
import importlib
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from aether.events import EventBus
from aether_gateway.browser_senses.bootstrap import (
    BootstrapRateLimitError,
    BootstrapStateError,
    BrowserSenseBootstrapService,
    DeviceCredentialError,
    SessionCredentialError,
)
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from fastapi.testclient import TestClient

ORIGIN = "https://aethers.my.id"
BROWSER_HEADERS = {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _device_key() -> tuple[ec.EllipticCurvePrivateKey, dict[str, str]]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    numbers = private_key.public_key().public_numbers()
    jwk = {
        "kty": "EC",
        "crv": "P-256",
        "x": _b64url(numbers.x.to_bytes(32, "big")),
        "y": _b64url(numbers.y.to_bytes(32, "big")),
        "ext": True,
        "key_ops": ["verify"],
    }
    return private_key, jwk


def _sign(
    private_key: ec.EllipticCurvePrivateKey, challenge: str, *, raw: bool = False
) -> str:
    signature = private_key.sign(challenge.encode("utf-8"), ec.ECDSA(hashes.SHA256()))
    if raw:
        r, s = decode_dss_signature(signature)
        signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return _b64url(signature)


def _reload_server(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AETHER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AETHER_OPERATOR_TOKEN", "founder-browser-secret")
    monkeypatch.setenv("AETHER_OPERATOR_ID", "founder")
    monkeypatch.setenv("AUTH_SECRET_KEY", "a" * 48)
    monkeypatch.setenv("AETHER_SENSE_WORKER_TOKEN", "worker-secret")
    monkeypatch.setenv("AETHER_FLEET_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("TELEGRAM_ENABLED", "false")
    monkeypatch.setenv("AETHER_SENSES_ORIGIN", ORIGIN)
    sys.modules.pop("aether_gateway.api.server", None)
    return importlib.import_module("aether_gateway.api.server")


def _pair(
    client: TestClient, private_key, public_jwk, verifier: bytes
) -> tuple[dict, str]:
    requested = client.post(
        "/api/browser-senses/bootstrap/requests",
        headers=BROWSER_HEADERS,
        json={
            "device_label": "Dee Android Chrome",
            "client_mode": "pwa",
            "capabilities": ["text", "microphone", "speaker", "camera"],
            "public_key_jwk": public_jwk,
            "verifier_hash": hashlib.sha256(verifier).hexdigest(),
        },
    )
    assert requested.status_code == 201, requested.text
    assert requested.headers["cache-control"] == "no-store"
    bootstrap = requested.json()
    assert bootstrap["state"] == "pending"
    assert len(bootstrap["confirmation_code"]) == 6
    assert bootstrap["client_proof"] not in json.dumps(bootstrap["request"])

    pending = client.post(
        f"/api/browser-senses/bootstrap/requests/{bootstrap['bootstrap_id']}/status",
        headers={
            **BROWSER_HEADERS,
            "X-Aether-Bootstrap-Proof": bootstrap["client_proof"],
        },
    )
    assert pending.status_code == 200
    assert pending.json()["state"] == "pending"

    listed = client.get(
        "/api/browser-senses/bootstrap/requests?status=pending",
        headers={
            **BROWSER_HEADERS,
            "X-Aether-Operator-Token": "founder-browser-secret",
        },
    )
    assert listed.status_code == 200
    card = listed.json()["requests"][0]
    assert card["confirmation_code"] == bootstrap["confirmation_code"]
    assert card["device_label"] == "Dee Android Chrome"
    assert "client_proof" not in listed.text
    assert "verifier" not in listed.text

    decision = client.post(
        f"/api/browser-senses/bootstrap/requests/{bootstrap['bootstrap_id']}/decision",
        headers={
            **BROWSER_HEADERS,
            "X-Aether-Operator-Token": "founder-browser-secret",
        },
        json={"approved": True, "reason": "Confirmation code matched"},
    )
    assert decision.status_code == 200, decision.text
    assert decision.json()["state"] == "approved"

    bad_exchange = client.post(
        f"/api/browser-senses/bootstrap/requests/{bootstrap['bootstrap_id']}/exchange",
        headers={
            **BROWSER_HEADERS,
            "X-Aether-Bootstrap-Proof": bootstrap["client_proof"],
        },
        json={
            "verifier": _b64url(verifier),
            "device_signature": _b64url(b"not-a-signature"),
        },
    )
    assert bad_exchange.status_code == 401

    exchange = client.post(
        f"/api/browser-senses/bootstrap/requests/{bootstrap['bootstrap_id']}/exchange",
        headers={
            **BROWSER_HEADERS,
            "X-Aether-Bootstrap-Proof": bootstrap["client_proof"],
        },
        json={
            "verifier": _b64url(verifier),
            "device_signature": _sign(
                private_key, bootstrap["exchange_challenge"], raw=True
            ),
        },
    )
    assert exchange.status_code == 200, exchange.text
    assert exchange.headers["cache-control"] == "no-store"
    assert exchange.json()["device"]["state"] == "active"
    assert "device_credential" not in exchange.text
    device_cookie = exchange.cookies.get("__Host-aether_device")
    assert device_cookie
    set_cookie = exchange.headers["set-cookie"]
    assert "Secure" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=strict" in set_cookie
    assert "Path=/" in set_cookie
    assert "Domain=" not in set_cookie

    replay = client.post(
        f"/api/browser-senses/bootstrap/requests/{bootstrap['bootstrap_id']}/exchange",
        headers={
            **BROWSER_HEADERS,
            "X-Aether-Bootstrap-Proof": bootstrap["client_proof"],
        },
        json={
            "verifier": _b64url(verifier),
            "device_signature": _sign(private_key, bootstrap["exchange_challenge"]),
        },
    )
    assert replay.status_code == 409
    assert replay.cookies.get("__Host-aether_device") is None
    return exchange.json()["device"], device_cookie


def test_pairing_cookie_session_csrf_and_revocation(
    tmp_path: Path, monkeypatch
) -> None:
    server = _reload_server(tmp_path, monkeypatch)
    private_key, public_jwk = _device_key()
    verifier = b"v" * 32

    with TestClient(server.app, base_url=ORIGIN) as client:
        page = client.get("/senses")
        assert page.status_code == 200
        assert "operatorToken" not in page.text
        assert "Founder/operator token" not in page.text
        assert page.headers["cache-control"] == "no-store"
        assert "frame-ancestors 'self'" in page.headers["content-security-policy"]

        wrong_origin = client.post(
            "/api/browser-senses/bootstrap/requests",
            headers={
                "Origin": "https://attacker.invalid",
                "Sec-Fetch-Site": "cross-site",
            },
            json={},
        )
        assert wrong_origin.status_code == 403

        device, device_cookie = _pair(client, private_key, public_jwk, verifier)

        raw_operator_path = client.post(
            "/api/browser-senses/session",
            headers={
                **BROWSER_HEADERS,
                "X-Aether-Operator-Token": "founder-browser-secret",
            },
            json={
                "display_name": "Founder",
                "capabilities": ["text"],
                "challenge_id": "operator-token-cannot-create-a-session",
                "device_signature": "not-a-device-signature",
            },
        )
        assert raw_operator_path.status_code in {401, 403}

        challenge = client.post(
            "/api/browser-senses/session/challenges",
            headers=BROWSER_HEADERS,
        )
        assert challenge.status_code == 201, challenge.text
        session_challenge = challenge.json()

        issued = client.post(
            "/api/browser-senses/session",
            headers=BROWSER_HEADERS,
            json={
                "display_name": "Founder",
                "capabilities": ["text", "camera"],
                "challenge_id": session_challenge["challenge_id"],
                "device_signature": _sign(private_key, session_challenge["challenge"]),
            },
        )
        assert issued.status_code == 200, issued.text
        assert issued.headers["cache-control"] == "no-store"
        payload = issued.json()
        assert payload["session"]["principal"] == "founder"
        assert payload["session"]["metadata"]["device_id"] == device["device_id"]
        assert "browser_session_token" not in issued.text
        csrf = payload["csrf_nonce"]
        assert csrf
        senses_cookie = issued.cookies.get("__Host-aether_senses")
        assert senses_cookie
        assert senses_cookie != device_cookie
        assert "HttpOnly" in issued.headers["set-cookie"]
        assert "Secure" in issued.headers["set-cookie"]
        assert "SameSite=strict" in issued.headers["set-cookie"]
        assert "Domain=" not in issued.headers["set-cookie"]

        challenge_replay = client.post(
            "/api/browser-senses/session",
            headers=BROWSER_HEADERS,
            json={
                "display_name": "Founder",
                "capabilities": ["text"],
                "challenge_id": session_challenge["challenge_id"],
                "device_signature": _sign(private_key, session_challenge["challenge"]),
            },
        )
        assert challenge_replay.status_code == 401

        missing_csrf = client.post(
            "/api/browser-senses/session/active",
            headers=BROWSER_HEADERS,
            json={"transport": "http-keyframe"},
        )
        assert missing_csrf.status_code == 403

        active = client.post(
            "/api/browser-senses/session/active",
            headers={**BROWSER_HEADERS, "X-Aether-CSRF": csrf},
            json={"transport": "http-keyframe"},
        )
        assert active.status_code == 200, active.text
        assert active.json()["state"] == "active"
        heartbeat = client.post(
            "/api/browser-senses/session/status",
            headers={**BROWSER_HEADERS, "X-Aether-CSRF": csrf},
        )
        assert heartbeat.status_code == 200
        assert heartbeat.json()["session_id"] == payload["session"]["session_id"]

        revoked = client.delete(
            f"/api/browser-senses/devices/{device['device_id']}",
            headers={
                **BROWSER_HEADERS,
                "X-Aether-Operator-Token": "founder-browser-secret",
            },
        )
        assert revoked.status_code == 200
        assert revoked.json()["sessions_closed"] == 1

        revoked_heartbeat = client.post(
            "/api/browser-senses/session/status",
            headers={**BROWSER_HEADERS, "X-Aether-CSRF": csrf},
        )
        assert revoked_heartbeat.status_code == 401

        after_revoke = client.post(
            "/api/browser-senses/text",
            headers={**BROWSER_HEADERS, "X-Aether-CSRF": csrf},
            json={
                "text": "This must not reach cognition",
                "turn_id": "turn-after-revoke",
                "correlation_id": "corr-after-revoke",
                "generation": 0,
            },
        )
        assert after_revoke.status_code == 401

    journal = (tmp_path / "home" / "events" / "browser-senses.jsonl").read_text(
        encoding="utf-8"
    )
    assert verifier.decode() not in journal
    assert device_cookie not in journal
    assert senses_cookie not in journal
    assert csrf not in journal


def test_bootstrap_rate_limit_and_expiry_are_deterministic(tmp_path: Path) -> None:
    current = datetime(2026, 8, 7, 0, 0, tzinfo=timezone.utc)
    service = BrowserSenseBootstrapService(
        tmp_path / "bootstrap.sqlite3",
        event_bus=EventBus(tmp_path / "events.jsonl"),
        secret="r" * 48,
        allowed_origin=ORIGIN,
        now=lambda: current,
    )
    _, public_jwk = _device_key()
    with pytest.raises(ValueError):
        service.request_pairing(
            public_key_jwk={**public_jwk, "d": _b64url(b"private-material")},
            verifier_hash=hashlib.sha256(b"private-jwk").hexdigest(),
            device_label="Invalid private JWK",
            client_mode="browser",
            capabilities=("text",),
            source="203.0.113.99",
        )
    for index in range(5):
        service.request_pairing(
            public_key_jwk=public_jwk,
            verifier_hash=hashlib.sha256(f"verifier-{index}".encode()).hexdigest(),
            device_label=f"Device {index}",
            client_mode="browser",
            capabilities=("text",),
            source="203.0.113.7",
        )
    with (
        sqlite3.connect(tmp_path / "bootstrap.sqlite3") as conn,
        pytest.raises(sqlite3.IntegrityError, match="append-only"),
    ):
        conn.execute("UPDATE browser_pairing_requests SET device_label='tampered'")
    with pytest.raises(BootstrapRateLimitError):
        service.request_pairing(
            public_key_jwk=public_jwk,
            verifier_hash=hashlib.sha256(b"sixth").hexdigest(),
            device_label="Device 6",
            client_mode="browser",
            capabilities=("text",),
            source="203.0.113.7",
        )

    current += timedelta(seconds=601)
    for index in range(25):
        service.request_pairing(
            public_key_jwk=public_jwk,
            verifier_hash=hashlib.sha256(f"global-{index}".encode()).hexdigest(),
            device_label=f"Global device {index}",
            client_mode="browser",
            capabilities=("text",),
            source=f"198.51.100.{index + 1}",
        )
    with pytest.raises(BootstrapRateLimitError):
        service.request_pairing(
            public_key_jwk=public_jwk,
            verifier_hash=hashlib.sha256(b"global-31").hexdigest(),
            device_label="Global device 31",
            client_mode="browser",
            capabilities=("text",),
            source="192.0.2.31",
        )

    first = service.list_requests(state="expired")[0]
    assert first["state"] == "expired"
    with pytest.raises(PermissionError):
        service.status(first["bootstrap_id"], client_proof="wrong")


def test_denied_pairing_is_replay_safe_and_cannot_exchange(
    tmp_path: Path, monkeypatch
) -> None:
    server = _reload_server(tmp_path, monkeypatch)
    private_key, public_jwk = _device_key()
    verifier = b"d" * 32
    with TestClient(server.app, base_url=ORIGIN) as client:
        requested = client.post(
            "/api/browser-senses/bootstrap/requests",
            headers=BROWSER_HEADERS,
            json={
                "device_label": "Unknown browser",
                "client_mode": "browser",
                "capabilities": ["text"],
                "public_key_jwk": public_jwk,
                "verifier_hash": hashlib.sha256(verifier).hexdigest(),
            },
        ).json()
        decision_headers = {
            **BROWSER_HEADERS,
            "X-Aether-Operator-Token": "founder-browser-secret",
        }
        denied = client.post(
            f"/api/browser-senses/bootstrap/requests/{requested['bootstrap_id']}/decision",
            headers=decision_headers,
            json={"approved": False, "reason": "Device was not requested by Dee"},
        )
        assert denied.status_code == 200
        assert denied.json()["state"] == "denied"
        replay = client.post(
            f"/api/browser-senses/bootstrap/requests/{requested['bootstrap_id']}/decision",
            headers=decision_headers,
            json={"approved": False, "reason": "Network retry"},
        )
        assert replay.status_code == 200
        assert replay.json()["replayed"] is True

        exchange = client.post(
            f"/api/browser-senses/bootstrap/requests/{requested['bootstrap_id']}/exchange",
            headers={
                **BROWSER_HEADERS,
                "X-Aether-Bootstrap-Proof": requested["client_proof"],
            },
            json={
                "verifier": _b64url(verifier),
                "device_signature": _sign(private_key, requested["exchange_challenge"]),
            },
        )
        assert exchange.status_code == 409
        assert exchange.cookies.get("__Host-aether_device") is None


def test_device_and_session_absolute_and_idle_lifetimes(tmp_path: Path) -> None:
    current = datetime(2026, 8, 7, 0, 0, tzinfo=timezone.utc)
    service = BrowserSenseBootstrapService(
        tmp_path / "bootstrap.sqlite3",
        event_bus=EventBus(tmp_path / "events.jsonl"),
        secret="l" * 48,
        allowed_origin=ORIGIN,
        now=lambda: current,
    )
    private_key, public_jwk = _device_key()
    verifier = b"i" * 32
    requested = service.request_pairing(
        public_key_jwk=public_jwk,
        verifier_hash=hashlib.sha256(verifier).hexdigest(),
        device_label="Lifetime test device",
        client_mode="browser",
        capabilities=("text",),
        source="203.0.113.10",
    )
    service.decide(
        requested["bootstrap_id"],
        approved=True,
        principal="founder",
        reason="test",
        channel="test",
    )
    exchanged = service.exchange(
        requested["bootstrap_id"],
        client_proof=requested["client_proof"],
        verifier=_b64url(verifier),
        device_signature=_sign(private_key, requested["exchange_challenge"]),
    )
    device = service.authenticate_device(exchanged["credential"])

    csrf = service.bind_session(
        session_id="idle-session",
        device_id=device["device_id"],
        session_credential="idle-credential",
        expires_at=(current + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
    )
    current += timedelta(seconds=901)
    with pytest.raises(SessionCredentialError):
        service.authenticate_session("idle-credential", csrf_nonce=csrf)

    active_csrf = service.bind_session(
        session_id="active-session",
        device_id=device["device_id"],
        session_credential="active-credential",
        expires_at=(current + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
    )
    service.mark_session_state("active-session", "active")
    current += timedelta(seconds=901)
    assert (
        service.authenticate_session("active-credential", csrf_nonce=active_csrf)[
            "state"
        ]
        == "active"
    )
    current += timedelta(seconds=2700)
    with pytest.raises(SessionCredentialError):
        service.authenticate_session("active-credential", csrf_nonce=active_csrf)

    current += timedelta(days=7, seconds=1)
    with pytest.raises(DeviceCredentialError):
        service.authenticate_device(exchanged["credential"])


def test_approved_pairing_still_expires_at_120_seconds(tmp_path: Path) -> None:
    current = datetime(2026, 8, 7, 0, 0, tzinfo=timezone.utc)
    service = BrowserSenseBootstrapService(
        tmp_path / "bootstrap.sqlite3",
        event_bus=EventBus(tmp_path / "events.jsonl"),
        secret="e" * 48,
        allowed_origin=ORIGIN,
        now=lambda: current,
    )
    private_key, public_jwk = _device_key()
    verifier = b"e" * 32
    requested = service.request_pairing(
        public_key_jwk=public_jwk,
        verifier_hash=hashlib.sha256(verifier).hexdigest(),
        device_label="Expiring approved device",
        client_mode="browser",
        capabilities=("text",),
        source="203.0.113.11",
    )
    service.decide(
        requested["bootstrap_id"],
        approved=True,
        principal="founder",
        reason="test",
        channel="test",
    )
    current += timedelta(seconds=121)
    with pytest.raises(BootstrapStateError):
        service.exchange(
            requested["bootstrap_id"],
            client_proof=requested["client_proof"],
            verifier=_b64url(verifier),
            device_signature=_sign(private_key, requested["exchange_challenge"]),
        )
    assert (
        service.list_requests(state="expired")[0]["bootstrap_id"]
        == requested["bootstrap_id"]
    )
