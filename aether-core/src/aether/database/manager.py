"""
Centralized Database Connection Manager for Aether Core
======================================================
Replaces scattered DB_PATH declarations across 15+ modules with a unified factory.
Provides SQLite WAL mode, busy timeout, immediate writes, and connection helpers.
"""

import sqlite3
from pathlib import Path

from aether.paths import get_paths


def get_connection(db_path: Path | str, wal_mode: bool = True, timeout: float = 10.0) -> sqlite3.Connection:
    """
    Get a configured SQLite database connection.
    
    Args:
        db_path: Path to the SQLite database file
        wal_mode: Enable Write-Ahead Logging (default: True)
        timeout: Busy timeout in seconds (default: 10.0)
        
    Returns:
        sqlite3.Connection configured with Row factory and WAL mode
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(str(path), timeout=timeout, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    
    if wal_mode:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        
    return conn


def get_db(db_name: str = "aether_hub") -> sqlite3.Connection:
    """
    Convenience accessor for Aether Core databases by name.
    
    Supported db_names:
        - "aether_hub" or "hub": aether_hub.db
        - "consciousness": consciousness.db
        - "beliefs": beliefs.db
        - "concepts": concepts.db
        - "dreams": dreams.db
        - "goals": goals.db
        - "predictions": predictions.db
        - "decisions": decisions.db
        - "knowledge_graph": knowledge_graph.db
        - "self_model": self_model.db
        - "world_model": world_model.db
        - "governance": governance_ledger.db
        - "shared_memory": shared_memory.db
    """
    paths = get_paths()
    
    mapping = {
        "aether_hub": paths.aether_hub_db,
        "hub": paths.aether_hub_db,
        "consciousness": paths.consciousness_db,
        "beliefs": paths.beliefs_db,
        "concepts": paths.concepts_db,
        "dreams": paths.dreams_db,
        "goals": paths.goals_db,
        "predictions": paths.predictions_db,
        "decisions": paths.decisions_db,
        "knowledge_graph": paths.knowledge_graph_db,
        "self_model": paths.self_model_db,
        "world_model": paths.world_model_db,
        "governance": paths.governance_db,
        "shared_memory": paths.shared_memory_db,
    }
    
    target_path = mapping.get(db_name.lower())
    if not target_path:
        raise ValueError(f"Unknown database name '{db_name}'. Available: {list(mapping.keys())}")
        
    return get_connection(target_path)
