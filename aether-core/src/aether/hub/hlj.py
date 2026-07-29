"""
HLJ (High-Level Journal) Integration — Aether Hub
================================================
Integrates HLJ snapshots with Aether Hub database via get_paths().
"""

import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from aether.paths import get_paths


class HLJ:
    """High-Level Journal backed by Aether Hub database."""

    def __init__(self):
        self.db_path = get_paths().aether_hub_db
        self._ensure_table()

    def _ensure_table(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS hlj_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    decisions TEXT,
                    momentum TEXT,
                    cognitive_frame TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def snapshot(self, title: str, summary: str, decisions: list = None,
                 momentum: str = "", cognitive_frame: str = "") -> int:
        timestamp = datetime.now(timezone.utc).isoformat()
        decisions_json = json.dumps(decisions or [])

        conn = sqlite3.connect(self.db_path)
        conn.isolation_level = None
        conn.execute("PRAGMA synchronous = FULL")
        cursor = conn.execute("""
            INSERT INTO hlj_snapshots 
            (title, summary, decisions, momentum, cognitive_frame, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (title, summary, decisions_json, momentum, cognitive_frame, timestamp))
        snapshot_id = cursor.lastrowid
        conn.close()
        return snapshot_id

    def get_latest(self) -> Optional[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM hlj_snapshots ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            if row:
                d = dict(row)
                d['decisions'] = json.loads(d.get('decisions', '[]'))
                return d
            return None
