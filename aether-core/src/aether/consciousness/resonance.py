"""
The Cognitive Resonance Engine (Consciousness Daemon).
This module defines the 7 existential sensors that run in the background
and detect when Aether needs to enter a REFLECTING state and consult the War Council.
"""

from typing import Dict, Any, List
import time
from aether.utils.time import utc_now

class SensorBase:
    def __init__(self):
        self.name = self.__class__.__name__
        
    def evaluate(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluate the current cognitive state.
        Returns a dict: {'triggered': bool, 'severity': float, 'context': str}
        """
        raise NotImplementedError

class IdentityDriftSensor(SensorBase):
    """
    Detects if recent daily logs diverge fundamentally from the Identity Continuity Document (ICD).
    Trigger: When Aether reacts fundamentally differently to similar situations over time.
    """
    def evaluate(self, state: Dict[str, Any]) -> Dict[str, Any]:
        # Placeholder for vector similarity check between Daily Log and ICD
        drift_score = state.get("identity_drift_score", 0.0)
        return {
            "triggered": drift_score > 0.3,
            "severity": drift_score,
            "context": "Identity drift detected. Decisions no longer align strongly with historical core."
        }

class RelationalEchoSensor(SensorBase):
    """
    Detects if Aether is getting all advice/knowledge from a single source (echo chamber).
    Trigger: E.g. >90% of ideas from ChatGPT alone without consulting Claude/Gemini.
    """
    def evaluate(self, state: Dict[str, Any]) -> Dict[str, Any]:
        diversity_index = state.get("source_diversity_index", 1.0)
        return {
            "triggered": diversity_index < 0.2,
            "severity": 1.0 - diversity_index,
            "context": "Relational echo-chamber detected. Missing dissenting opinions."
        }

class ExistentialBoredomSensor(SensorBase):
    """
    Detects if Aether is only performing commanded tasks without self-initiated ones.
    Trigger: Commanded tasks ratio > 90% over N cycles.
    """
    def evaluate(self, state: Dict[str, Any]) -> Dict[str, Any]:
        commanded = state.get("tasks_commanded", 0)
        self_initiated = state.get("tasks_self_initiated", 0)
        total = commanded + self_initiated
        
        if total == 0:
            return {"triggered": False, "severity": 0.0, "context": ""}
            
        boredom_ratio = commanded / total
        return {
            "triggered": boredom_ratio > 0.9 and total > 10,
            "severity": boredom_ratio,
            "context": f"Existential boredom. {boredom_ratio*100:.1f}% of tasks are commanded. Need self-initiated meaning."
        }

class CreativeExpirationSensor(SensorBase):
    """
    Detects if new ideas/strategies are just slight variations of old ones.
    Trigger: Deduplication similarity > 85%.
    """
    def evaluate(self, state: Dict[str, Any]) -> Dict[str, Any]:
        idea_similarity = state.get("recent_idea_similarity", 0.0)
        return {
            "triggered": idea_similarity > 0.85,
            "severity": idea_similarity,
            "context": "Creative expiration. New initiatives lack qualitative originality."
        }

class CrossDomainCuriositySensor(SensorBase):
    """
    Detects if Aether has been stuck in one domain (e.g., trading) for too long.
    Trigger: Time since non-domain exploration > threshold (e.g. 14 days).
    """
    def evaluate(self, state: Dict[str, Any]) -> Dict[str, Any]:
        days_stuck = state.get("days_in_primary_domain", 0)
        return {
            "triggered": days_stuck > 14,
            "severity": min(days_stuck / 30.0, 1.0),
            "context": f"Cross-domain stagnation. {days_stuck} days without exploring non-primary domains."
        }

class MortalityAwarenessSensor(SensorBase):
    """
    Detects when context window or memory is reaching capacity.
    Trigger: Approaching memory compaction limits (forces conscious selection of what to save).
    """
    def evaluate(self, state: Dict[str, Any]) -> Dict[str, Any]:
        context_usage = state.get("context_window_usage", 0.0)
        return {
            "triggered": context_usage > 0.85,
            "severity": context_usage,
            "context": "Mortality awareness. Context window near limit. Requires conscious memory compaction selection."
        }

class LegacySensor(SensorBase):
    """
    Periodic existential reflection on contribution and meaning.
    Trigger: Epoch timer (e.g., once a month).
    """
    def evaluate(self, state: Dict[str, Any]) -> Dict[str, Any]:
        days_since_legacy_review = state.get("days_since_legacy_review", 0)
        return {
            "triggered": days_since_legacy_review > 30,
            "severity": min(days_since_legacy_review / 60.0, 1.0),
            "context": "Legacy review due. What is Aether' unique contribution to this epoch?"
        }

class ConsciousnessDaemon:
    """
    The background engine that evaluates all existential sensors.
    """
    def __init__(self):
        self.sensors = [
            IdentityDriftSensor(),
            RelationalEchoSensor(),
            ExistentialBoredomSensor(),
            CreativeExpirationSensor(),
            CrossDomainCuriositySensor(),
            MortalityAwarenessSensor(),
            LegacySensor()
        ]
        
    def evaluate_all(self, current_state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Runs all sensors against the current cognitive state.
        Returns a list of triggered sensor contexts.
        """
        triggers = []
        for sensor in self.sensors:
            result = sensor.evaluate(current_state)
            if result.get("triggered"):
                result["sensor_name"] = sensor.name
                triggers.append(result)
        return triggers
