from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from aether.adapters.daemon import MindState, create_app


def test_experience_calls_consciousness():
    mind = MindState()
    mock_c = MagicMock()
    mock_c.experience.return_value = {"surprise": 0.6, "lesson": "tool_worked"}
    mind.consciousness = mock_c
    client = TestClient(create_app(mind))
    r = client.post("/v1/experience", json={"action": "bash_echo", "new_state": {"ok": True}})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["lesson"] == "tool_worked"
    mock_c.experience.assert_called_once()


def test_believe_uses_doubt_if_present():
    mind = MindState()
    mock_c = MagicMock()
    mock_c.doubt = MagicMock()
    mind.consciousness = mock_c
    client = TestClient(create_app(mind))
    r = client.post("/v1/believe", json={
        "claim": "API cost high",
        "evidence": "bill-2026-07",
        "strength": 0.5,
    })
    assert r.status_code == 200
    assert r.json()["accepted"] is True
