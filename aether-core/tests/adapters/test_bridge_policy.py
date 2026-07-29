import importlib.util
from pathlib import Path


def _load():
    p = Path(__file__).resolve().parents[2] / "plugins/runtime_host/aether_bridge/policy.py"
    spec = importlib.util.spec_from_file_location("bridge_policy", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_terminal_rm_is_irreversible():
    m = _load()
    assert m.is_irreversible_tool("terminal", {"command": "rm -rf /tmp/x"}) is True


def test_read_file_not_irreversible():
    m = _load()
    assert m.is_irreversible_tool("read_file", {"path": "a.txt"}) is False


def test_estimate_amount_from_args():
    m = _load()
    assert m.estimate_amount_usd("open_trade", {"amount_usd": 12}) == 12.0


def test_should_gate_when_spend_or_irreversible():
    m = _load()
    assert m.should_gate("terminal", {"command": "rm foo"}) is True
    assert m.should_gate("read_file", {"path": "x"}) is False
