"""
Session State Management — Aether Hub Integration
================================================
Unified session state management integrated with Aether Hub database.
Replaces legacy file-based sync with SQLite-backed persistence via get_paths().
"""

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

from aether.paths import get_paths


class SessionState:
    """Unified session state management backed by Aether Hub database."""

    def __init__(self):
        self.db_path = get_paths().aether_hub_db
        self._ensure_table()

    def _ensure_table(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS session_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def _set(self, key: str, value: Any):
        timestamp = datetime.now(timezone.utc).isoformat()
        value_json = json.dumps(value)

        conn = sqlite3.connect(self.db_path)
        conn.isolation_level = None
        conn.execute("PRAGMA synchronous = FULL")
        conn.execute("""
            INSERT OR REPLACE INTO session_state (key, value, updated_at)
            VALUES (?, ?, ?)
        """, (key, value_json, timestamp))
        conn.close()

    def _get(self, key: str, default=None) -> Any:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT value FROM session_state WHERE key = ?",
                (key,)
            )
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
            return default

    def get_state(self) -> dict:
        return {
            'tasks': self._get('tasks', []),
            'decisions': self._get('decisions', []),
            'blockers': self._get('blockers', []),
            'handoff': self._get('handoff', ''),
            'last_updated': self._get('last_updated', '')
        }

    def update_task(self, task_id: str, status: str, description: str):
        tasks = self._get('tasks', [])
        found = False
        for task in tasks:
            if task.get('id') == task_id:
                task['status'] = status
                task['description'] = description
                task['updated_at'] = datetime.now(timezone.utc).isoformat()
                found = True
                break
        if not found:
            tasks.append({
                'id': task_id,
                'status': status,
                'description': description,
                'updated_at': datetime.now(timezone.utc).isoformat()
            })
        self._set('tasks', tasks)
        self._set('last_updated', datetime.now(timezone.utc).isoformat())

    def add_decision(self, decision: str, reason: str):
        decisions = self._get('decisions', [])
        decisions.append({
            'decision': decision,
            'reason': reason,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
        self._set('decisions', decisions)
        self._set('last_updated', datetime.now(timezone.utc).isoformat())

    def set_handoff(self, handoff_message: str):
        self._set('handoff', handoff_message)
        self._set('last_updated', datetime.now(timezone.utc).isoformat())
