from pathlib import Path
import importlib.util
import yaml


def _load_validator():
    path = Path(__file__).parents[1] / "scripts" / "validate_memory_fabric.py"
    spec = importlib.util.spec_from_file_location("validate_memory_fabric", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_memory_fabric_invariants():
    module = _load_validator()
    repo_root = Path(__file__).parents[1]
    assert module.validate(repo_root) == []


def test_native_memory_activation_requires_no_external_provider_install():
    root = Path(__file__).parents[1]
    data = yaml.safe_load((root / "configs" / "memory_fabric.yaml").read_text(encoding="utf-8"))
    policy = data["installation_policy"]
    assert data["status"] == "active"
    assert policy["install_all_evaluated_providers"] is False
    assert policy["core_external_memory_dependencies"] == []
    assert policy["enabled_provider"] == "aether_native_sqlite"
