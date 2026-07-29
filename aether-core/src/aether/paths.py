"""
Platform-Agnostic Path Management for Aether Core
==================================================
Centralized path resolution via AETHER_HOME environment variable.
Replaces all hardcoded Windows/Linux paths across the codebase.
"""

import os
import platform
from pathlib import Path


def get_aether_home() -> Path:
    """Resolve AETHER_HOME — works on Windows, Linux, macOS."""
    env = os.environ.get("AETHER_HOME")
    if env:
        return Path(env)
    
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
        return Path(base) / "Aether"
    else:  # Linux, macOS
        return Path.home() / ".aether"


class AetherPaths:
    """Centralized path accessors for Aether Core."""
    
    def __init__(self, home: Path | None = None):
        self._home = home or get_aether_home()
        self._home.mkdir(parents=True, exist_ok=True)
    
    @property
    def home(self) -> Path:
        return self._home

    @property
    def db(self) -> Path:
        p = self.home / "db"
        p.mkdir(exist_ok=True)
        return p

    @property
    def logs(self) -> Path:
        p = self.home / "logs"
        p.mkdir(exist_ok=True)
        return p

    @property
    def sessions(self) -> Path:
        p = self.home / "sessions"
        p.mkdir(exist_ok=True)
        return p

    @property
    def queue(self) -> Path:
        p = self.home / "queue"
        p.mkdir(exist_ok=True)
        return p

    @property
    def genome(self) -> Path:
        p = self.home / "genome"
        p.mkdir(exist_ok=True)
        return p

    @property
    def memory(self) -> Path:
        p = self.home / "memory"
        p.mkdir(exist_ok=True)
        return p

    @property
    def obsidian_vault(self) -> Path:
        p = self.home / "obsidian" / "vault"
        p.mkdir(parents=True, exist_ok=True)
        return p


    # Database file paths
    @property
    def consciousness_db(self) -> Path:
        return self.db / "consciousness.db"

    @property
    def beliefs_db(self) -> Path:
        return self.db / "beliefs.db"

    @property
    def concepts_db(self) -> Path:
        return self.db / "concepts.db"

    @property
    def dreams_db(self) -> Path:
        return self.db / "dreams.db"

    @property
    def goals_db(self) -> Path:
        return self.db / "goals.db"

    @property
    def predictions_db(self) -> Path:
        return self.db / "predictions.db"

    @property
    def decisions_db(self) -> Path:
        return self.db / "decisions.db"

    @property
    def knowledge_graph_db(self) -> Path:
        return self.db / "knowledge_graph.db"

    @property
    def self_model_db(self) -> Path:
        return self.db / "self_model.db"

    @property
    def world_model_db(self) -> Path:
        return self.db / "world_model.db"

    @property
    def governance_db(self) -> Path:
        return self.db / "governance_ledger.db"

    @property
    def aether_hub_db(self) -> Path:
        return self.db / "aether_hub.db"

    @property
    def shared_memory_db(self) -> Path:
        return self.db / "shared_memory.db"

    @property
    def cognitive_sessions_db(self) -> Path:
        return self.sessions / "cognitive-sessions.sqlite3"

    @property
    def canonical_memory_db(self) -> Path:
        return self.memory / "canonical-episodes.sqlite3"

    @property
    def retrieval_index_db(self) -> Path:
        return self.memory / "retrieval-index.sqlite3"

    @property
    def knowledge_proposals_db(self) -> Path:
        return self.memory / "knowledge-proposals.sqlite3"

    @property
    def skills(self) -> Path:
        p = self.home / "skills"
        p.mkdir(exist_ok=True)
        return p

    @property
    def skill_factory_db(self) -> Path:
        return self.skills / "skill-factory.sqlite3"

    @property
    def skill_registry(self) -> Path:
        p = self.skills / "registry"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def missions(self) -> Path:
        p = self.home / "missions"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def mission_orchestrator_db(self) -> Path:
        return self.missions / "mission-orchestrator.sqlite3"


_paths_instance: AetherPaths | None = None


def get_paths() -> AetherPaths:
    """Get global AetherPaths singleton."""
    global _paths_instance
    if _paths_instance is None:
        _paths_instance = AetherPaths()
    return _paths_instance


def reset_paths(custom_home: Path | None = None) -> AetherPaths:
    """Reset global paths instance (useful for testing)."""
    global _paths_instance
    _paths_instance = AetherPaths(home=custom_home)
    return _paths_instance
