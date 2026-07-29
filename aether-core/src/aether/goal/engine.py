"""
Goal Engine.
Goals in Aether V2 are treated as Canonical Knowledge Objects (CKOs) in the OPERATIONAL orbit.
"""

from pathlib import Path
from typing import Any, Dict, List

from aether.utils.ids import new_id
from aether.utils.jsonio import write_json
from aether.utils.time import utc_now
from aether.knowledge.cka_physics import CanonicalKnowledgeObject, CognitiveOrbit
from aether.goal.workspace import ensure_goal_workspace, read_goals, write_goals
from aether.obsidian import write_note

def score_goal(goal: dict[str, Any]) -> dict[str, Any]:
    # Simplified scoring for Wave 2
    progress = 0.0
    krs = goal.get("key_results", [])
    if krs:
        progress = sum(float(kr.get("progress", 0.0)) for kr in krs) / len(krs)
        
    northstar = float(goal.get("northstar_score", 0.5))
    score = (northstar * 0.6) + (progress * 0.4)
    
    return {
        "score": round(score, 4),
        "progress": round(progress, 4)
    }

def create_goal(root: Path, title: str, description: str = "", horizon: str = "monthly") -> dict[str, Any]:
    ensure_goal_workspace(root)
    goals = read_goals(root)
    
    # We represent a Goal as a CKO in the OPERATIONAL orbit
    cko = CanonicalKnowledgeObject(
        surface_text=f"Goal: {title}. {description}",
        subject="Aether",
        predicate="aims_to",
        object=title,
        context=horizon,
        current_orbit=CognitiveOrbit.OPERATIONAL,
        epistemic_confidence=1.0,
        evidence_strength=0.5,
        identity_relevance=0.8
    )
    
    goal = {
        "goal_id": cko.id, # Link goal ID to CKO ID
        "title": title,
        "description": description,
        "horizon": horizon,
        "status": "active",
        "key_results": [],
        "northstar_score": 0.8, # Mocked for now
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    
    score_data = score_goal(goal)
    goal["goal_score"] = score_data["score"]
    
    # Write to Obsidian Second Brain
    body = f"""# Goal: {title}
    
## Description
{description}

## Metrics
- Horizon: {horizon}
- Status: active
- Score: {score_data['score']}
- Progress: {score_data['progress']}

## Key Results
- No key results yet.
"""
    write_note(
        root,
        "objective",
        f"Goal - {title}",
        body,
        metadata={"goal_id": goal["goal_id"], "orbit": "OPERATIONAL"},
        folder="01_Objectives",
        overwrite=True
    )
    
    goals.append(goal)
    write_goals(root, goals)
    return {"ok": True, "goal": goal}

def add_key_result(root: Path, goal_id: str, metric: str, target: float) -> dict[str, Any]:
    goals = read_goals(root)
    goal = next((g for g in goals if g["goal_id"] == goal_id), None)
    if not goal:
        return {"ok": False, "error": "Goal not found"}
        
    kr = {
        "kr_id": new_id("kr"),
        "metric": metric,
        "target": target,
        "current": 0.0,
        "progress": 0.0
    }
    goal.setdefault("key_results", []).append(kr)
    
    score_data = score_goal(goal)
    goal["goal_score"] = score_data["score"]
    goal["updated_at"] = utc_now()
    
    write_goals(root, goals)
    return {"ok": True, "goal": goal}
