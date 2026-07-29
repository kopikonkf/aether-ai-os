import importlib.util
from pathlib import Path
from unittest.mock import patch


def _load_bridge():
    pol = Path(__file__).resolve().parents[2] / "plugins/runtime_host/aether_bridge/policy.py"
    spec = importlib.util.spec_from_file_location("bridge_policy", pol)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_gated_tool_requires_gate():
    m = _load_bridge()
    assert m.should_gate("terminal", {"command": "rm secret"}) is True


def test_client_down_is_alive_false():
    from aether.adapters.client import AetherClient
    with patch("aether.adapters.client.requests.get", side_effect=ConnectionError):
        assert AetherClient(timeout=0.2).is_alive() is False
