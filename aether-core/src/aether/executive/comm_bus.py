"""
Inter-Entity Communication Bus (CommBus)
========================================
SQLite-backed message bus for Aether entities and sub-agents.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from aether.database.manager import get_db


class CommBus:
    """Inter-entity communication bus."""

    def __init__(self, agent_name: str = "aether_core"):
        self.agent_name = agent_name
        self.conn = get_db("shared_memory")
        self._init_db()

    def _init_db(self):
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    message_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    read INTEGER DEFAULT 0
                )
            """)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS agents (
                    agent_name TEXT PRIMARY KEY,
                    last_heartbeat DATETIME,
                    status TEXT DEFAULT 'active'
                )
            """)

    def register(self):
        """Register agent or update heartbeat."""
        now = datetime.now(timezone.utc).isoformat()
        with self.conn:
            self.conn.execute("""
                INSERT OR REPLACE INTO agents (agent_name, last_heartbeat, status)
                VALUES (?, ?, 'active')
            """, (self.agent_name, now))

    def send(self, recipient: str, message_type: str, payload: Dict[str, Any]) -> int:
        """Send message to another entity/agent."""
        with self.conn:
            cursor = self.conn.execute("""
                INSERT INTO messages (sender, recipient, message_type, payload)
                VALUES (?, ?, ?, ?)
            """, (self.agent_name, recipient, message_type, json.dumps(payload)))
            return cursor.lastrowid

    def receive(self, limit: int = 10, mark_read: bool = True) -> List[Dict[str, Any]]:
        """Receive unread messages for this agent."""
        with self.conn:
            cursor = self.conn.execute("""
                SELECT id, sender, recipient, message_type, payload, created_at
                FROM messages
                WHERE recipient = ? OR recipient = 'broadcast' AND read = 0
                ORDER BY id ASC LIMIT ?
            """, (self.agent_name, limit))
            rows = cursor.fetchall()
            
            messages = []
            msg_ids = []
            for row in rows:
                msg_ids.append(row["id"])
                messages.append({
                    "id": row["id"],
                    "sender": row["sender"],
                    "recipient": row["recipient"],
                    "type": row["message_type"],
                    "payload": json.loads(row["payload"]),
                    "created_at": row["created_at"],
                })

            if mark_read and msg_ids:
                self.conn.execute(
                    f"UPDATE messages SET read = 1 WHERE id IN ({','.join('?'*len(msg_ids))})",
                    msg_ids
                )

            return messages
