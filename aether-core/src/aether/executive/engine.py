"""
Circadian Executive Loop.
Runs the daily operations of Aether.
At the end of a cycle (or when idle), it triggers the Consciousness Daemon
to check for existential resonance (boredom, identity drift, etc.).
"""

from pathlib import Path
from typing import Any, Callable, Dict
import time

from aether.utils.time import utc_now
from aether.executive.workspace import ensure_executive_workspace
from aether.consciousness.resonance import ConsciousnessDaemon
from aether.contracts.memory import MemoryKind, MemoryProvenance, MemoryRecord
from aether.memory import SQLiteCanonicalMemoryStore
from aether.paths import AetherPaths

class CircadianExecutiveEngine:
    def __init__(self, workspace_root: Path, reasoner: Callable[[str], str] | None = None):
        self.root = workspace_root
        ensure_executive_workspace(self.root)
        self.consciousness = ConsciousnessDaemon()
        self.canonical_memory = SQLiteCanonicalMemoryStore(AetherPaths(self.root).canonical_memory_db)
        self.reasoner = reasoner
        
    def _gather_cognitive_state(self) -> Dict[str, Any]:
        """Gathers metrics for the existential sensors."""
        # In a full implementation, this reads from the actual databases.
        # For now, we mock some metrics to allow simulation.
        return {
            "identity_drift_score": 0.1,
            "source_diversity_index": 0.5,
            "tasks_commanded": 15,
            "tasks_self_initiated": 2, # Will trigger boredom if ratio > 0.9
            "recent_idea_similarity": 0.4,
            "days_in_primary_domain": 15, # Will trigger cross-domain curiosity
            "context_window_usage": 0.4,
            "days_since_legacy_review": 5
        }
        
    def execute_tick(self) -> Dict[str, Any]:
        """
        Executes a single mechanical tick of the Executive Loop.
        Normally this picks a task and executes it.
        """
        # Mechanical execution logic goes here (simplified for Wave 3)
        return {"status": "executed", "task": "example_task"}
        
    def trigger_reflection(self, triggers: list) -> None:
        """
        Transitions Aether to REFLECTING state and calls the War Council.
        """
        print(f"Entering REFLECTING state. Triggers: {[t['sensor_name'] for t in triggers]}")
        
        # Build prompt for War Council
        context = "\n".join([f"- {t['context']}" for t in triggers])
        prompt = f"I am experiencing the following cognitive states:\n{context}\nWhat should my next initiative be to resolve this?"
        
        # Instead of calling Third Eyes API, Aether consults its own brain.
        print("Consulting Internal Brain for Synthesis...")
        
        synthesis_prompt = f"Triggers: {context}\n\nBased on my core identity and these existential triggers, what is the best epiphany or synthesis of these ideas? If an action is required, explicitly state what needs to be done."
        
        try:
            if self.reasoner is None:
                raise RuntimeError("No cognitive reasoner injected into executive engine")
            epiphany = self.reasoner(synthesis_prompt)
            print("Synthesis complete.")
            
            # Since Aether is 100% autonomous, if it feels the need to take action
            # we will pass it back to the router with a prompt that forces tool execution if needed
            action_prompt = f"You just had this epiphany:\n{epiphany}\nDo you need to delegate any tasks or make any codebase changes to resolve your triggers? If yes, use your tools. If no, just reply 'No action needed'."
            self.reasoner(action_prompt)
            
            # Reflection is evidence, not knowledge. Store it canonically and mark
            # it as an explicit curator candidate. The curator still requires
            # independent evidence and trusted governance before promotion.
            print("Recording reflection as canonical curator evidence...")
            record = self.canonical_memory.append_sync(MemoryRecord(
                key=f"reflection:{utc_now()}",
                value={"reflection": epiphany},
                namespace="episodes",
                kind=MemoryKind.REFLECTION,
                content=epiphany,
                metadata={
                    "knowledge_candidate": {
                        "claim": epiphany,
                        "claim_key": f"internal-reflection:{utc_now()[:10]}",
                        "polarity": 0,
                    },
                    "promotion_status": "not_promoted",
                },
                provenance=MemoryProvenance(
                    source="internal_reflection",
                    observed_at=utc_now(),
                ),
            ))
            print(f"Reflection recorded for governed curation: {record.record_id}")
            
        except Exception as e:
            epiphany = f"Failed to synthesize internal reflection: {str(e)}"
            print(epiphany)
            
        # Write to Obsidian (Life Reflection Note)
        body = f"""# Life Reflection Note
        
## Triggers
{context}

## Internal Epiphany
{epiphany}
"""
        from aether.obsidian import write_note
        write_note(
            self.root,
            "reflection",
            f"Reflection - {utc_now().replace(':','-')}",
            body,
            metadata={"tags": ["sniper/reflection", "existential_trigger"]},
            folder="04_Reflections",
            overwrite=True
        )
        
    def run_daily_cycle(self) -> None:
        """
        Runs the daily mechanical tasks, then triggers the biological clock.
        """
        print("Starting daily mechanical cycle...")
        # Run mechanical ticks
        for _ in range(3):
            self.execute_tick()
            
        print("Daily cycle complete. Checking biological clock...")
        
        # Biological Clock Trigger
        current_state = self._gather_cognitive_state()
        active_triggers = self.consciousness.evaluate_all(current_state)
        
        if active_triggers:
            self.trigger_reflection(active_triggers)
        else:
            print("No existential triggers fired. Going to sleep.")
