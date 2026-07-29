"""Continuous Evolution Engine — internal governed evolution lane."""
from .engine import InternalEvolutionEngine
from .governance import EvolutionBlocked, EvolutionPolicy, InternalEvolutionGovernor
from .intake import capability_gap, evolution_fingerprint, trigger_from_event
from .store import EvolutionDecisionConflict, EvolutionNotFound, SQLiteEvolutionStore

__all__ = [
    "InternalEvolutionEngine",
    "EvolutionBlocked",
    "EvolutionPolicy",
    "InternalEvolutionGovernor",
    "EvolutionDecisionConflict",
    "EvolutionNotFound",
    "SQLiteEvolutionStore",
    "capability_gap",
    "evolution_fingerprint",
    "trigger_from_event",
]
