"""Evidence-first knowledge curation and legacy compatibility exports."""

from .curator import MemoryCurator
from .governance import KnowledgeGovernor, KnowledgePromotionPolicy
from .projection import ObsidianKnowledgeProjector
from .store import SQLiteKnowledgeProposalStore, canonical_proposal_hash, normalize_claim
from .workspace import ensure_knowledge_workspace
from .lifecycle import KnowledgeLifecycle
from .indexer import build_knowledge_index, knowledge_status, validate_knowledge_workspace

__all__ = [
    "MemoryCurator",
    "KnowledgeGovernor",
    "KnowledgePromotionPolicy",
    "ObsidianKnowledgeProjector",
    "SQLiteKnowledgeProposalStore",
    "canonical_proposal_hash",
    "normalize_claim",
    "ensure_knowledge_workspace",
    "KnowledgeLifecycle",
    "build_knowledge_index",
    "knowledge_status",
    "validate_knowledge_workspace",
]
