"""
Knowledge Lifecycle.
Manages the promotion of Canonical Knowledge Objects (CKOs) through Cognitive Orbits.
"""

from typing import Dict, Any, List, Optional
from pathlib import Path

from aether.events import EventBus
from aether.utils.ids import new_id
from aether.utils.jsonio import read_json, write_json
from aether.utils.time import utc_now
from aether.knowledge.cka_physics import CanonicalKnowledgeObject, CognitiveOrbit, CKAPhysicsEngine
from aether.knowledge.workspace import ensure_knowledge_workspace, registry_path
from aether.obsidian import write_note

class KnowledgeLifecycle:
    def __init__(self, workspace_root: Path):
        self.root = workspace_root
        ensure_knowledge_workspace(self.root)
        self.physics = CKAPhysicsEngine()
        self.registry_file = registry_path(self.root)
        
    def _read_ckos(self) -> List[Dict[str, Any]]:
        return read_json(self.registry_file, default=[])
        
    def _write_ckos(self, ckos: List[Dict[str, Any]]) -> None:
        write_json(self.registry_file, ckos)
        
    def ingest_claim(self, claim_text: str, source_id: str, confidence: float = 0.5) -> CanonicalKnowledgeObject:
        """Ingests a new claim into the EPHEMERAL orbit."""
        cko = CanonicalKnowledgeObject(
            surface_text=claim_text,
            epistemic_confidence=confidence,
            current_orbit=CognitiveOrbit.EPHEMERAL
        )
        
        # In a real system, NLP would extract subject, predicate, object here.
        # For now, we store the raw text in surface_text.
        
        ckos = self._read_ckos()
        # Convert dataclass to dict for JSON storage
        ckos.append(self._to_dict(cko))
        self._write_ckos(ckos)
        
        return cko
        
    def promote(self, cko_id: str) -> Optional[CanonicalKnowledgeObject]:
        """Direct promotion is disabled.

        Claims must enter the evidence-backed MemoryCurator pipeline and receive
        a trusted, immutable governance decision before becoming knowledge.
        """
        raise PermissionError(
            "Direct KnowledgeLifecycle promotion is disabled; use MemoryCurator.decide()"
        )

    def _write_to_obsidian(self, cko: CanonicalKnowledgeObject) -> None:
        body = f"""# Canonical Knowledge: {cko.id}
        
## Claim
{cko.surface_text}

## Epistemic Gravity
- Confidence: {cko.epistemic_confidence}
- Evidence Strength: {cko.evidence_strength}
- Identity Relevance: {cko.identity_relevance}
- Calculated Gravity: {cko.cognitive_gravity}
- Current Orbit: {cko.current_orbit.name}
"""
        write_note(
            self.root,
            "knowledge",
            f"CKO-{cko.id}",
            body,
            metadata={"orbit": cko.current_orbit.name},
            folder="05_Knowledge",
            overwrite=True
        )
        
    def _to_dict(self, cko: CanonicalKnowledgeObject) -> Dict[str, Any]:
        return {
            "id": cko.id,
            "created_at": cko.created_at,
            "updated_at": cko.updated_at,
            "surface_text": cko.surface_text,
            "subject": cko.subject,
            "predicate": cko.predicate,
            "object": cko.object,
            "context": cko.context,
            "epistemic_confidence": cko.epistemic_confidence,
            "evidence_strength": cko.evidence_strength,
            "identity_relevance": cko.identity_relevance,
            "current_orbit": cko.current_orbit.name,
            "previous_revision_id": cko.previous_revision_id
        }
        
    def _from_dict(self, d: Dict[str, Any]) -> CanonicalKnowledgeObject:
        cko = CanonicalKnowledgeObject()
        cko.id = d["id"]
        cko.created_at = d["created_at"]
        cko.updated_at = d["updated_at"]
        cko.surface_text = d["surface_text"]
        cko.subject = d["subject"]
        cko.predicate = d["predicate"]
        cko.object = d["object"]
        cko.context = d["context"]
        cko.epistemic_confidence = d["epistemic_confidence"]
        cko.evidence_strength = d["evidence_strength"]
        cko.identity_relevance = d["identity_relevance"]
        cko.current_orbit = CognitiveOrbit[d["current_orbit"]]
        cko.previous_revision_id = d["previous_revision_id"]
        return cko
