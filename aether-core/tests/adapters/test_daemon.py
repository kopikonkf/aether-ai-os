from fastapi.testclient import TestClient
from aether.adapters.daemon import create_app


def test_health_ok():
    client = TestClient(create_app())
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["dna_ok"] is True


def test_who_am_i():
    client = TestClient(create_app())
    r = client.get("/v1/who_am_i")
    assert r.status_code == 200
    body = r.json()
    assert body["alive"] is True
    assert body["name"]


def test_evaluate_safe_action_approved():
    client = TestClient(create_app())
    r = client.post("/v1/north_star_evaluate", json={
        "action": "read_config",
        "reason": "inspect tool policy before change",
        "amount_usd": 0,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["approved"] is True
    assert body["escalate_to_dee"] is False


def test_evaluate_high_spend_escalates():
    client = TestClient(create_app())
    r = client.post("/v1/north_star_evaluate", json={
        "action": "open_trade",
        "reason": "momentum signal",
        "amount_usd": 50.0,
        "proposal_type": "open_trade",
    })
    assert r.status_code == 200
    body = r.json()
    # default Y=10 → escalate
    assert body["escalate_to_dee"] is True
