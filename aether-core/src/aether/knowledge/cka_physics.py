"""
Canonical Knowledge Architecture (CKA) Physics Engine.
This module defines the physics of knowledge in Aether. It replaces traditional "Memory".
Knowledge is not saved; it is "promoted" to different cognitive orbits based on Epistemic Gravity.
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum
from aether.utils.time import utc_now
from aether.utils.ids import new_id

class CognitiveOrbit(Enum):
    EPHEMERAL = 0    # Fleeting data, tool outputs, raw text
    WORKING = 1      # Current task context
    OPERATIONAL = 2  # Active projects, current goals
    STABLE = 3       # Architectural knowledge, long-term strategies
    CORE = 4         # DNA, Genome, Constitution, Identity (Immutable)

@dataclass
class CanonicalKnowledgeObject:
    """
    The fundamental atomic unit of knowledge in Aether.
    A CKO is not a fact; it is a claim with varying degrees of evidence and gravity.
    """
    id: str = field(default_factory=lambda: new_id(prefix="cko"))
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    
    # Layer 1: Surface
    surface_text: str = ""
    
    # Layer 2: Semantic
    subject: str = ""
    predicate: str = ""
    object: str = ""
    context: str = ""
    
    # Layer 3: Epistemic (The "Why should I believe this?")
    epistemic_confidence: float = 0.5  # 0.0 to 1.0
    evidence_strength: float = 0.0     # 0.0 to 1.0
    identity_relevance: float = 0.0    # How much this defines Aether
    
    # Physics State
    current_orbit: CognitiveOrbit = CognitiveOrbit.WORKING
    previous_revision_id: Optional[str] = None
    
    @property
    def cognitive_gravity(self) -> float:
        """
        Calculates the mass/gravity of this knowledge.
        Higher gravity knowledge is harder to overwrite and takes precedence in retrieval.
        """
        # Gravity is heavily influenced by identity relevance and evidence strength
        return (self.identity_relevance * 0.6) + (self.evidence_strength * 0.4)

class CKAPhysicsEngine:
    def __init__(self):
        pass
        
    def calculate_promotion_threshold(self, target_orbit: CognitiveOrbit) -> float:
        """Returns the required cognitive gravity to enter a specific orbit."""
        thresholds = {
            CognitiveOrbit.EPHEMERAL: 0.0,
            CognitiveOrbit.WORKING: 0.2,
            CognitiveOrbit.OPERATIONAL: 0.5,
            CognitiveOrbit.STABLE: 0.8,
            CognitiveOrbit.CORE: 1.0 # Requires God-level authority (Human)
        }
        return thresholds.get(target_orbit, 1.0)
        
    def evaluate_orbital_promotion(self, cko: CanonicalKnowledgeObject) -> CognitiveOrbit:
        """
        Evaluates a CKO's gravity and returns the highest orbit it qualifies for.
        """
        gravity = cko.cognitive_gravity
        
        # We don't auto-promote to CORE.
        if gravity >= self.calculate_promotion_threshold(CognitiveOrbit.STABLE):
            return CognitiveOrbit.STABLE
        elif gravity >= self.calculate_promotion_threshold(CognitiveOrbit.OPERATIONAL):
            return CognitiveOrbit.OPERATIONAL
        elif gravity >= self.calculate_promotion_threshold(CognitiveOrbit.WORKING):
            return CognitiveOrbit.WORKING
        return CognitiveOrbit.EPHEMERAL
        
    def apply_revision(self, old_cko: CanonicalKnowledgeObject, new_claim: str, 
                       new_confidence: float) -> CanonicalKnowledgeObject:
        """
        Event Sourcing implementation. Never overwrite, always revise.
        Creates a new CKO pointing to the old one.
        """
        new_cko = CanonicalKnowledgeObject(
            surface_text=new_claim,
            subject=old_cko.subject,
            predicate=old_cko.predicate,
            object=old_cko.object,
            context=old_cko.context,
            epistemic_confidence=new_confidence,
            evidence_strength=old_cko.evidence_strength, # Requires independent evaluation
            identity_relevance=old_cko.identity_relevance,
            current_orbit=old_cko.current_orbit,
            previous_revision_id=old_cko.id
        )
        return new_cko
