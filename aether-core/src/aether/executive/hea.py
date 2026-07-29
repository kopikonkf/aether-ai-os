"""
Aether Executive Assistant (HEA) / Chief of Staff.
This module is responsible for the Continuity Layer. It intercepts Aether startup,
reads the Obsidian Vault and state, and generates a Morning Briefing to prevent amnesia.
"""

from typing import Dict, Any, List
from pathlib import Path
from aether.utils.jsonio import read_json
from aether.knowledge.workspace import registry_path

class AetherExecutiveAssistant:
    def __init__(self, workspace_root: Path):
        self.root = workspace_root
        
    def _get_active_goals(self) -> List[Dict[str, Any]]:
        goals_file = self.root / "runtime_state" / "goals" / "goals.json"
        if not goals_file.exists():
            return []
        goals = read_json(goals_file, default=[])
        return [g for g in goals if g.get("status") == "active"]
        
    def _get_recent_knowledge(self) -> List[Dict[str, Any]]:
        registry = registry_path(self.root)
        if not registry.exists():
            return []
        ckos = read_json(registry, default=[])
        # Sort by updated_at descending and get top 3 stable/operational
        relevant = [c for c in ckos if c.get("current_orbit") in ["OPERATIONAL", "STABLE"]]
        relevant.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return relevant[:3]
        
    def generate_morning_briefing(self) -> str:
        """
        Builds the context string that gets injected into Aether Core on startup.
        """
        active_goals = self._get_active_goals()
        recent_knowledge = self._get_recent_knowledge()
        
        briefing = [
            "Good morning, Aether. I am your Executive Assistant (HEA).",
            "Here is your continuity briefing:\n",
            "### ACTIVE GOALS"
        ]
        
        if active_goals:
            for g in active_goals:
                score = g.get("goal_score", 0.0)
                briefing.append(f"- {g.get('title')} (Score: {score})")
        else:
            briefing.append("- No active goals. Awaiting your initiative.")
            
        briefing.append("\n### RECENT KNOWLEDGE / DECISIONS")
        if recent_knowledge:
            for cko in recent_knowledge:
                briefing.append(f"- [{cko.get('current_orbit')}] {cko.get('surface_text')}")
        else:
            briefing.append("- No recent operational or stable knowledge recorded.")
            
        briefing.append("\n### RECOMMENDED NEXT STEP")
        briefing.append("Please evaluate the active goals or check your internal resonance sensors for new initiatives.")
        
        return "\n".join(briefing)
