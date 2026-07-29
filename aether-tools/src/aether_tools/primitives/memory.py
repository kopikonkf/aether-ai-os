import sqlite3
import json
from pathlib import Path
from aether_tools.base import Tool, ToolResult


class MemoryTool(Tool):
    name = "memory"
    spec = 'op=store/recall/search key="..." value="..." query="..."'

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts
                USING fts5(key, value, tokenize='porter unicode61')
            """)
            conn.commit()
        finally:
            conn.close()

    def _store(self, key: str, value: str) -> str:
        conn = sqlite3.connect(str(self.db_path))
        try:
            existing = conn.execute("SELECT rowid FROM memory_fts WHERE key = ?", (key,)).fetchone()
            if existing:
                conn.execute("UPDATE memory_fts SET value = ? WHERE key = ?", (value, key))
                return f"Updated memory: {key}"
            else:
                conn.execute("INSERT INTO memory_fts (key, value) VALUES (?, ?)", (key, value))
                return f"Stored memory: {key}"
        finally:
            conn.commit()
            conn.close()

    def _recall(self, key: str) -> str:
        conn = sqlite3.connect(str(self.db_path))
        try:
            row = conn.execute("SELECT value FROM memory_fts WHERE key = ?", (key,)).fetchone()
            if row:
                return f"Memory [{key}]:\n{row[0]}"
            return f"Memory not found: {key}"
        finally:
            conn.close()

    def _search(self, query: str) -> str:
        conn = sqlite3.connect(str(self.db_path))
        try:
            rows = conn.execute("""
                SELECT key, snippet(memory_fts, 1, '<b>', '</b>', '...', 32)
                FROM memory_fts WHERE value MATCH ?
                LIMIT 10
            """, (query,)).fetchall()
            if not rows:
                return f"No memories matching: {query}"
            results = [f"  - {k}: {s}" for k, s in rows]
            return f"Memories matching '{query}':\n" + "\n".join(results)
        finally:
            conn.close()


    def validate(self, op: str = "", key: str = "", value: str = "", query: str = "", **kwargs) -> ToolResult:
        if op not in {"store", "recall", "search"}:
            return ToolResult(False, "", None, "op required (store/recall/search)")
        if op == "store" and (not key or not value):
            return ToolResult(False, "", None, "store requires key and value")
        if op == "recall" and not key:
            return ToolResult(False, "", None, "recall requires key")
        if op == "search" and not query:
            return ToolResult(False, "", None, "search requires query")
        return ToolResult(True, "Memory preflight passed.")

    def __call__(self, op: str = "", key: str = "", value: str = "", query: str = "", **kwargs) -> ToolResult:
        preflight = self.validate(op=op, key=key, value=value, query=query)
        if not preflight.ok:
            return preflight

        if op == "store":
            if not key or not value:
                return ToolResult(False, "", None, "store requires key and value")
            try:
                out = self._store(key, value)
                return ToolResult(True, out)
            except Exception as e:
                return ToolResult(False, "", None, f"Store failed: {e}")

        elif op == "recall":
            if not key:
                return ToolResult(False, "", None, "recall requires key")
            try:
                out = self._recall(key)
                return ToolResult(True, out)
            except Exception as e:
                return ToolResult(False, "", None, f"Recall failed: {e}")

        elif op == "search":
            if not query:
                return ToolResult(False, "", None, "search requires query")
            try:
                out = self._search(query)
                return ToolResult(True, out)
            except Exception as e:
                return ToolResult(False, "", None, f"Search failed: {e}")

        else:
            return ToolResult(False, "", None, f"Unknown op: {op} (use store/recall/search)")
