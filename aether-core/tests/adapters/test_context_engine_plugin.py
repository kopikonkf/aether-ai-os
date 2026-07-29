from unittest.mock import MagicMock


def test_build_mind_prefix_uses_who_am_i():
    import importlib.util
    from pathlib import Path
    p = Path(__file__).resolve().parents[2] / "plugins/runtime_host/context_engine/aether/engine.py"
    spec = importlib.util.spec_from_file_location("aether_engine", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    mock_client = MagicMock()
    mock_client.is_alive.return_value = True
    mock_client.who_am_i.return_value = MagicMock(
        name="Aether",
        narrative="mind online",
        stage="baby",
        mission="create value",
        values=["truthfulness"],
    )
    text = mod.build_mind_prefix(mock_client)
    assert "Aether" in text
    assert "baby" in text
    assert "mind online" in text


def test_build_mind_prefix_fail_safe_when_down():
    import importlib.util
    from pathlib import Path
    p = Path(__file__).resolve().parents[2] / "plugins/runtime_host/context_engine/aether/engine.py"
    spec = importlib.util.spec_from_file_location("aether_engine", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    mock_client = MagicMock()
    mock_client.is_alive.return_value = False
    text = mod.build_mind_prefix(mock_client)
    assert "FAIL-SAFE" in text or "unavailable" in text.lower()
