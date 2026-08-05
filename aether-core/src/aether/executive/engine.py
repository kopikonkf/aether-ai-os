"""
Circadian Executive Loop.
Runs the daily operations of Aether.
At the end of a cycle (or when idle), it triggers the Consciousness Daemon
to check for existential resonance (boredom, identity drift, etc.).
"""

from pathlib import Path
from typing import Any, Callable, Dict
import json
import time

from aether.utils.time import utc_now
from aether.executive.workspace import ensure_executive_workspace
from aether.consciousness.resonance import ConsciousnessDaemon
from aether.contracts.memory import MemoryKind, MemoryProvenance, MemoryRecord
from aether.memory import SQLiteCanonicalMemoryStore
from aether.paths import AetherPaths

# Cooldown before the same existential trigger may fire again. Without it, an
# unchanged sensor input (previously a hardcoded mock) re-writes a near-identical
# reflection every cycle, flooding 04_Reflections with duplicates.
REFLECTION_COOLDOWN_DAYS = 14
REFLECTION_STATE_REL = Path("runtime_state") / "reflection_state.json"

class CircadianExecutiveEngine:
    def __init__(self, workspace_root: Path, reasoner: Callable[[str], str] | None = None):
        self.root = workspace_root
        ensure_executive_workspace(self.root)
        self.consciousness = ConsciousnessDaemon()
        self.canonical_memory = SQLiteCanonicalMemoryStore(AetherPaths(self.root).canonical_memory_db)
        self.reasoner = reasoner

    def _state_path(self) -> Path:
        return AetherPaths(self.root).home / REFLECTION_STATE_REL

    def _load_reflection_state(self) -> Dict[str, Any]:
        try:
            path = self._state_path()
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except Exception as exc:
            print(f"Failed to load reflection state: {exc}")
        return {}

    def _save_reflection_state(self, state: Dict[str, Any]) -> None:
        try:
            path = self._state_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception as exc:
            print(f"Failed to save reflection state: {exc}")

    @staticmethod
    def _days_since(timestamp: str | None) -> int:
        if not timestamp:
            return 0
        try:
            return max(0, int((time.time() - float(timestamp)) / 86400))
        except (TypeError, ValueError):
            return 0

    def _gather_cognitive_state(self) -> Dict[str, Any]:
        """Gathers metrics for the existential sensors.

        Domain-stagnation now derives from real state instead of a hardcoded
        mock: days are measured since the last cross-domain reflection was
        written. First run without any state uses the original threshold
        default so the sensor still fires once.
        """
        state = self._load_reflection_state()
        last = state.get("last_cross_domain_reflection_at")
        days_in_primary_domain = 15 if not last else self._days_since(str(last))
        return {
            "identity_drift_score": 0.1,
            "source_diversity_index": 0.5,
            "tasks_commanded": 15,
            "tasks_self_initiated": 2, # Will trigger boredom if ratio > 0.9
            "recent_idea_similarity": 0.4,
            "days_in_primary_domain": days_in_primary_domain,
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
        
        # Cooldown guard: do not re-write a near-identical reflection for the
        # same existential trigger while it is still in cooldown.
        has_cross_domain = any(t.get("sensor_name") == "CrossDomainCuriositySensor" for t in triggers)
        if has_cross_domain:
            state = self._load_reflection_state()
            last = state.get("last_cross_domain_reflection_at")
            if last and self._days_since(str(last)) < REFLECTION_COOLDOWN_DAYS:
                print(f"Skipping cross-domain reflection: within {REFLECTION_COOLDOWN_DAYS}-day cooldown.")
                return
        
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
        
        # A reflection was emitted for the cross-domain trigger; record when so
        # the loop stays quiet until the cooldown elapses.
        if has_cross_domain:
            state = self._load_reflection_state()
            state["last_cross_domain_reflection_at"] = str(time.time())
            self._save_reflection_state(state)
        
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
