from unittest.mock import MagicMock, patch
from aether.adapters.client import AetherClient


def test_who_am_i_parses_response():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "name": "Aether",
        "narrative": "I am Aether",
        "stage": "baby",
        "alive": True,
    }
    with patch("aether.adapters.client.requests.get", return_value=mock_resp):
        c = AetherClient(base_url="http://127.0.0.1:8765")
        r = c.who_am_i()
    assert r.name == "Aether"
    assert r.alive is True


def test_evaluate_posts_body():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "approved": True,
        "alignment_score": 0.9,
        "warnings": [],
        "escalate_to_dee": False,
    }
    with patch("aether.adapters.client.requests.post", return_value=mock_resp) as post:
        c = AetherClient(base_url="http://127.0.0.1:8765")
        r = c.evaluate(action="read_file", reason="inspect config", amount_usd=0)
    assert r.approved is True
    assert post.called


def test_health_down_returns_false():
    with patch("aether.adapters.client.requests.get", side_effect=ConnectionError):
        c = AetherClient(base_url="http://127.0.0.1:8765", timeout=0.5)
        assert c.is_alive() is False
