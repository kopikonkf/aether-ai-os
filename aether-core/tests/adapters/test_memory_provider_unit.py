import importlib.util
from pathlib import Path
from unittest.mock import MagicMock


def _load():
    p = Path(__file__).resolve().parents[2] / "plugins/runtime_host/memory/aether/provider.py"
    spec = importlib.util.spec_from_file_location("aether_mem", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_write_routes_to_canonical_episode_not_belief(tmp_path):
    mod = _load()
    client = MagicMock()
    provider = mod.AetherMemoryCore(client, canonical_path=tmp_path / "canonical.sqlite3")
    out = provider.write_operational("user prefers short answers", session_id="runtime:test")
    assert out["ok"] is True
    assert out["record_id"].startswith("mem.")
    client.believe.assert_not_called()


def test_prefetch_fail_safe(tmp_path):
    mod = _load()
    client = MagicMock()
    client.is_alive.return_value = False
    provider = mod.AetherMemoryCore(client, canonical_path=tmp_path / "canonical.sqlite3")
    assert provider.prefetch("hello") == ""
