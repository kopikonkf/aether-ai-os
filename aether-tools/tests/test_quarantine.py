import json
from pathlib import Path

from aether_tools.quarantine import BehaviorMonitor


def test_profile_observation_epoch_persists_across_restarts(tmp_path: Path):
    config = tmp_path / "security_profiles.yaml"
    config.write_text(
        """
profiles:
  strict: {}
quarantine:
  enabled: true
trust_metrics:
  upgrade_thresholds:
    strict_to_medium: 80
  min_observation_days:
    strict_to_medium: 7
""".strip(),
        encoding="utf-8",
    )
    state = tmp_path / "runtime_state" / "quarantine_state.json"

    first = BehaviorMonitor(config, state)
    profile_start_path = state.parent / "profile_start.json"
    assert profile_start_path.is_file()
    persisted = json.loads(profile_start_path.read_text(encoding="utf-8"))["start_time"]
    assert persisted == first.profile_start_time

    second = BehaviorMonitor(config, state)
    assert second.profile_start_time == persisted


def test_malformed_profile_epoch_is_repaired(tmp_path: Path):
    config = tmp_path / "security_profiles.yaml"
    config.write_text("profiles: {}\n", encoding="utf-8")
    state = tmp_path / "runtime_state" / "quarantine_state.json"
    state.parent.mkdir(parents=True)
    profile_start = state.parent / "profile_start.json"
    profile_start.write_text('{"start_time": "not-a-number"}', encoding="utf-8")

    monitor = BehaviorMonitor(config, state)
    persisted = json.loads(profile_start.read_text(encoding="utf-8"))["start_time"]
    assert persisted == monitor.profile_start_time
    assert isinstance(persisted, float)
