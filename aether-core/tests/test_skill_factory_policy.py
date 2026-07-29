from pathlib import Path
import yaml

from aether.skills import SkillFactoryPolicy


def test_packaged_skill_policy_is_aether_owned_and_governed():
    policy = SkillFactoryPolicy.load()
    assert policy.repeated_minimum_observations == 3
    assert policy.repeated_minimum_success_rate == 0.8
    assert policy.heldout_required is True
    assert "founder" in policy.trusted_principals
    assert "belief.promote" in policy.protected_capabilities


def test_machine_policy_forbids_self_activation_and_automatic_deletion():
    root = Path(__file__).resolve().parents[1]
    data = yaml.safe_load((root / "src" / "aether" / "skills" / "skill_factory.yaml").read_text(encoding="utf-8"))
    assert data["principles"]["owner"] == "aether"
    assert data["principles"]["runtime_installation"] == "adapter_owned"
    assert data["principles"]["automatic_activation"] == "forbidden"
    assert data["principles"]["automatic_deletion"] == "forbidden"
    assert data["principles"]["telemetry_may_change_identity"] is False
    assert data["principles"]["telemetry_may_change_beliefs"] is False
