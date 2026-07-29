from pathlib import Path
import yaml

from aether.knowledge import KnowledgePromotionPolicy


def test_packaged_knowledge_policy_requires_evidence_and_trusted_governance():
    policy = KnowledgePromotionPolicy.load()
    assert policy.minimum_supporting_evidence == 2
    assert policy.minimum_distinct_sources == 2
    assert policy.duplicate_proposals_blocked is True
    assert policy.unresolved_contradictions_blocked is True
    assert policy.require_trusted_principal is True


def test_machine_policy_forbids_automatic_belief_promotion():
    root = Path(__file__).resolve().parents[1]
    data = yaml.safe_load((root / "src" / "aether" / "knowledge" / "knowledge_promotion.yaml").read_text(encoding="utf-8"))
    assert data["principles"]["direct_conversation_to_knowledge"] == "forbidden"
    assert data["principles"]["direct_conversation_to_belief"] == "forbidden"
    assert data["principles"]["automatic_belief_promotion"] == "forbidden"
    assert data["principles"]["contradictions_must_remain_visible"] is True
