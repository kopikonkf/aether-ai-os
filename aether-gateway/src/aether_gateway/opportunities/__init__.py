"""Opportunity scout adapters and mission bridge."""
from .adapters import (
    Crawl4AIRestrictedAdapter, GenericPublicHttpAdapter, SourceCapabilityMesh, StaticCatalogAdapter,
)
from .mission_bridge import OpportunityMissionBridge
from .scout import AutonomousOpportunityScout, HeuristicOpportunityClaimExtractor

__all__ = [
    "AutonomousOpportunityScout", "Crawl4AIRestrictedAdapter", "GenericPublicHttpAdapter",
    "HeuristicOpportunityClaimExtractor", "OpportunityMissionBridge", "SourceCapabilityMesh", "StaticCatalogAdapter",
]
