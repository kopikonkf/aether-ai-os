from pathlib import Path

from aether.bootstrap import validate_bootstrap_policy


def test_founder_bootstrap_sequence_is_executable_and_valid() -> None:
    root = Path(__file__).resolve().parents[1]
    result = validate_bootstrap_policy(root / "src" / "aether" / "bootstrap" / "bootstrap.yaml")
    assert result.passed, result.errors
    assert result.policy["sequence"][0] == "empty_state"
    assert result.policy["sequence"][-1] == "honest_audit"
    assert result.policy["state_requirements"]["empty_state"]["memory_provider_required"] is False
