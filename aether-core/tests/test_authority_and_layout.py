from pathlib import Path
import yaml


def test_only_one_north_star_exists_in_core():
    root = Path(__file__).resolve().parents[1]
    source = root / "src"
    matches = [path for path in source.rglob("*.yaml") if path.name.replace("_", "").lower() == "northstar.yaml"]
    assert matches == [source / "aether" / "dna" / "north_star.yaml"]


def test_core_contains_no_architecture_document_corpus():
    root = Path(__file__).resolve().parents[1]
    assert not (root / "docs").exists()
    assert not (root / "ARCHITECTURE_RULES.md").exists()
    assert not (root / "src" / "aether" / "consciousness" / "MODULES.md").exists()


def test_north_star_defines_cross_niche_business_portfolio():
    root = Path(__file__).resolve().parents[1]
    data = yaml.safe_load((root / "src" / "aether" / "dna" / "north_star.yaml").read_text(encoding="utf-8"))
    policy = data["business_portfolio_policy"]
    assert policy["trading_role"] == "one_income_division_among_many"
    assert policy["trading_privileged"] is False
    assert policy["opportunity_scope"] == "cross_niche_and_open_ended"


def test_evolution_policy_uses_code_level_curator_boundaries():
    root = Path(__file__).resolve().parents[1]
    data = yaml.safe_load((root / "configs" / "evolution_policy.yaml").read_text(encoding="utf-8"))
    lifecycle = data["skill_lifecycle"]
    assert lifecycle["automatic_delete"] == "forbidden"
    assert lifecycle["backup_before_mutation"] is True
    assert lifecycle["arbitrary_terminal_or_filesystem_access"] == "forbidden"
    assert lifecycle["prompt_only_protection_is_sufficient"] is False


def test_model_provider_configuration_is_outside_core():
    root = Path(__file__).resolve().parents[1]
    assert not (root / "configs" / "llm_providers.yaml").exists()
    assert not (root / "src" / "aether" / "router" / "resource.py").exists()


def test_bootstrap_policy_is_machine_readable_runtime_asset():
    root = Path(__file__).resolve().parents[1]
    path = root / "src" / "aether" / "bootstrap" / "bootstrap.yaml"
    assert path.exists()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["authority"]["north_star"] == "src/aether/dna/north_star.yaml"
    assert data["state_requirements"]["belief_proposal"]["direct_conversation_to_belief"] == "forbidden"


def test_memory_policy_is_machine_readable_runtime_asset():
    root = Path(__file__).resolve().parents[1]
    path = root / "src" / "aether" / "memory" / "memory_fabric.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["status"] == "active"
    assert data["ownership"]["canonical_authority"] == "aether_core"
    assert data["operational"]["obsidian_projection"]["authority"] == "projection_only"


def test_runtime_memory_bridge_never_calls_belief_api():
    root = Path(__file__).resolve().parents[1]
    path = root / "plugins" / "runtime_host" / "memory" / "aether" / "provider.py"
    text = path.read_text(encoding="utf-8")
    assert ".believe(" not in text
    assert 'namespace="episodes"' in text
