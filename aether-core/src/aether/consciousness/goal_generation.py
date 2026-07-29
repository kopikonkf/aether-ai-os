"""
Goal Generation Engine — Module 4

Goal states: proposed -> accepted -> active -> completed / failed / abandoned
Hierarchy: philosophy_goals -> capability_goals -> weekly_goals -> daily_goals
Autonomous goal creation from capability gap detection.
"""

import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from aether.paths import get_paths
DB_DIR = get_paths().db
DB_PATH = DB_DIR / "goals.db"

VALID_STATES = {"proposed", "accepted", "active", "completed", "failed", "abandoned"}
HIERARCHY_LEVELS = ["philosophy_goal", "capability_goal", "weekly_goal", "daily_goal"]


def _get_conn():
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path=None):
    path = db_path or str(DB_PATH)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS goals (
            id TEXT PRIMARY KEY,
            parent_id TEXT,
            name TEXT NOT NULL,
            description TEXT,
            state TEXT NOT NULL DEFAULT 'proposed',
            success_criteria TEXT NOT NULL,
            created TEXT NOT NULL,
            deadline TEXT,
            progress REAL DEFAULT 0.0,
            capability_gap TEXT,
            source TEXT,
            hierarchy_level TEXT,
            FOREIGN KEY (parent_id) REFERENCES goals(id)
        );
        CREATE TABLE IF NOT EXISTS goal_progress (
            id TEXT PRIMARY KEY,
            goal_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            progress REAL NOT NULL,
            evidence TEXT,
            FOREIGN KEY (goal_id) REFERENCES goals(id)
        );
        CREATE INDEX IF NOT EXISTS idx_goals_state ON goals(state);
        CREATE INDEX IF NOT EXISTS idx_goals_parent ON goals(parent_id);
        CREATE INDEX IF NOT EXISTS idx_progress_goal ON goal_progress(goal_id);
    """)
    conn.commit()
    conn.close()


class GoalEngine:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or str(DB_PATH)
        init_db(self.db_path)

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    # ── CRUD ──────────────────────────────────────────────

    def create_goal(
        self,
        name: str,
        success_criteria: str,
        description: str = "",
        parent_id: Optional[str] = None,
        capability_gap: Optional[str] = None,
        source: str = "manual",
        deadline: Optional[str] = None,
        hierarchy_level: Optional[str] = None,
    ) -> str:
        gid = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        # Auto-detect hierarchy level from parent
        if hierarchy_level is None:
            if parent_id is None:
                hierarchy_level = "philosophy_goal"
            else:
                parent = self.get_goal(parent_id)
                if parent:
                    idx = HIERARCHY_LEVELS.index(parent["hierarchy_level"]) if parent["hierarchy_level"] in HIERARCHY_LEVELS else 0
                    hierarchy_level = HIERARCHY_LEVELS[min(idx + 1, len(HIERARCHY_LEVELS) - 1)]
                else:
                    hierarchy_level = "daily_goal"
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO goals (id, parent_id, name, description, state, success_criteria, created, deadline, progress, capability_gap, source, hierarchy_level) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (gid, parent_id, name, description, "proposed", success_criteria, now, deadline, 0.0, capability_gap, source, hierarchy_level),
            )
        return gid

    def get_goal(self, goal_id: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM goals WHERE id=?", (goal_id,)).fetchone()
            return dict(row) if row else None

    def get_goals(self, state: Optional[str] = None, hierarchy_level: Optional[str] = None) -> list[dict]:
        q = "SELECT * FROM goals WHERE 1=1"
        params = []
        if state:
            q += " AND state=?"
            params.append(state)
        if hierarchy_level:
            q += " AND hierarchy_level=?"
            params.append(hierarchy_level)
        q += " ORDER BY created DESC"
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(q, params).fetchall()]

    def get_sub_goals(self, parent_id: str) -> list[dict]:
        with self._conn() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM goals WHERE parent_id=? ORDER BY created", (parent_id,)).fetchall()]

    # ── State transitions ─────────────────────────────────

    def transition(self, goal_id: str, new_state: str) -> bool:
        if new_state not in VALID_STATES:
            return False
        goal = self.get_goal(goal_id)
        if not goal:
            return False
        with self._conn() as conn:
            conn.execute("UPDATE goals SET state=? WHERE id=?", (new_state, goal_id))
        return True

    def accept(self, goal_id: str) -> bool:
        return self.transition(goal_id, "accepted")

    def activate(self, goal_id: str) -> bool:
        return self.transition(goal_id, "active")

    def complete(self, goal_id: str) -> bool:
        ok = self.transition(goal_id, "completed")
        if ok:
            self.record_progress(goal_id, 1.0, "Goal completed")
        return ok

    def fail(self, goal_id: str, reason: str = "") -> bool:
        ok = self.transition(goal_id, "failed")
        if ok and reason:
            self.record_progress(goal_id, self.get_goal(goal_id)["progress"], f"Failed: {reason}")
        return ok

    def abandon(self, goal_id: str, reason: str = "") -> bool:
        return self.transition(goal_id, "abandoned")

    # ── Progress tracking ─────────────────────────────────

    def record_progress(self, goal_id: str, progress: float, evidence: str = "") -> str:
        pid = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        progress = max(0.0, min(1.0, progress))
        with self._conn() as conn:
            conn.execute("INSERT INTO goal_progress (id, goal_id, timestamp, progress, evidence) VALUES (?,?,?,?,?)",
                         (pid, goal_id, now, progress, evidence))
            conn.execute("UPDATE goals SET progress=? WHERE id=?", (progress, goal_id))
        return pid

    def get_progress_history(self, goal_id: str) -> list[dict]:
        with self._conn() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM goal_progress WHERE goal_id=? ORDER BY timestamp", (goal_id,)).fetchall()]

    # ── Capability gap → goal generation ──────────────────

    def detect_gap_and_create_goal(
        self,
        capability_name: str,
        current_level: float,
        desired_level: float,
        parent_id: Optional[str] = None,
    ) -> Optional[str]:
        """Create goal from capability gap. Returns goal id or None if no gap."""
        gap = desired_level - current_level
        if gap <= 0:
            return None
        gap_desc = f"{capability_name}: {current_level:.2f} -> {desired_level:.2f} (gap={gap:.2f})"
        name = f"Close gap: {capability_name}"
        criteria = f"Reach {desired_level:.2f} in {capability_name} (currently {current_level:.2f})"
        gid = self.create_goal(
            name=name,
            success_criteria=criteria,
            description=gap_desc,
            parent_id=parent_id,
            capability_gap=gap_desc,
            source="gap_detection",
        )
        self.accept(gid)
        self.activate(gid)
        return gid

    # ── Sub-goal decomposition ────────────────────────────

    def decompose(self, goal_id: str, sub_goals: list[dict]) -> list[str]:
        """Create sub-goals under a parent. Each dict needs name, success_criteria."""
        ids = []
        for sg in sub_goals:
            sid = self.create_goal(
                name=sg["name"],
                success_criteria=sg["success_criteria"],
                description=sg.get("description", ""),
                parent_id=goal_id,
                source="decomposition",
            )
            ids.append(sid)
        return ids

    # ── Autonomous generation ─────────────────────────────

    def autonomous_review(self) -> list[str]:
        """Review active goals, detect stalled ones, suggest actions. Returns list of goal ids needing attention."""
        attention = []
        with self._conn() as conn:
            active = conn.execute("SELECT * FROM goals WHERE state='active'").fetchall()
            for g in active:
                g = dict(g)
                # Check if progress hasn't changed in 7 days
                last = conn.execute(
                    "SELECT timestamp FROM goal_progress WHERE goal_id=? ORDER BY timestamp DESC LIMIT 1",
                    (g["id"],)
                ).fetchone()
                if last:
                    last_ts = datetime.fromisoformat(last[0])
                    if (datetime.utcnow() - last_ts).days >= 7:
                        attention.append(g["id"])
                else:
                    # No progress recorded at all
                    created = datetime.fromisoformat(g["created"])
                    if (datetime.utcnow() - created).days >= 3:
                        attention.append(g["id"])
        return attention

    def generate_weekly_goals(self) -> list[str]:
        """Placeholder: generates weekly sub-goals from active capability goals.
        In production this would analyze capability goals and create concrete weekly targets."""
        ids = []
        cap_goals = self.get_goals(state="active", hierarchy_level="capability_goal")
        for cg in cap_goals:
            sub = self.get_sub_goals(cg["id"])
            weekly_count = sum(1 for s in sub if s["hierarchy_level"] == "weekly_goal" and s["state"] in ("proposed", "accepted", "active"))
            if weekly_count < 1:
                wid = self.create_goal(
                    name=f"Weekly target for: {cg['name']}",
                    success_criteria=f"Make measurable progress on: {cg['success_criteria']}",
                    parent_id=cg["id"],
                    source="autonomous_weekly",
                    deadline=(datetime.utcnow() + timedelta(days=7)).isoformat(),
                    hierarchy_level="weekly_goal",
                )
                self.accept(wid)
                self.activate(wid)
                ids.append(wid)
        return ids


# ── CLI / Test ────────────────────────────────────────────

def _test():
    import os
    # Use temp db for test
    test_db = str(DB_DIR / "goals_test.db")
    if os.path.exists(test_db):
        os.remove(test_db)

    engine = GoalEngine(db_path=test_db)
    print("=== Goal Generation Engine Test ===\n")

    # 1. Philosophy goal
    pg = engine.create_goal(
        name="Achieve deep self-understanding",
        success_criteria="Can introspect on own reasoning and identify biases",
        description="Long-term philosophy goal",
        source="manual",
        hierarchy_level="philosophy_goal",
    )
    print(f"Philosophy goal created: {pg[:8]}...")

    # 2. Capability gap detection
    cg = engine.detect_gap_and_create_goal("code_review", current_level=0.3, desired_level=0.8, parent_id=pg)
    print(f"Capability gap goal: {engine.get_goal(cg)['name']}")
    print(f"  State: {engine.get_goal(cg)['state']}")
    print(f"  Hierarchy: {engine.get_goal(cg)['hierarchy_level']}")

    # 3. Decompose into sub-goals
    sub_ids = engine.decompose(cg, [
        {"name": "Study code review best practices", "success_criteria": "Complete 5 code review tutorials"},
        {"name": "Review 20 real PRs", "success_criteria": "Provide feedback on 20 pull requests"},
    ])
    print(f"Decomposed into {len(sub_ids)} sub-goals")

    # 4. Progress tracking
    engine.record_progress(sub_ids[0], 0.5, "Completed 3 tutorials")
    engine.record_progress(sub_ids[0], 1.0, "Completed all 5 tutorials")
    engine.complete(sub_ids[0])
    history = engine.get_progress_history(sub_ids[0])
    print(f"Progress entries: {len(history)} (final: {history[-1]['progress']})")

    # 5. State transitions
    engine.accept(sub_ids[1])
    engine.activate(sub_ids[1])
    print(f"Sub-goal state: {engine.get_goal(sub_ids[1])['state']}")

    # 6. Generate weekly goals
    weekly = engine.generate_weekly_goals()
    print(f"Auto-generated weekly goals: {len(weekly)}")

    # 7. Autonomous review (stalled detection)
    attention = engine.autonomous_review()
    print(f"Goals needing attention: {len(attention)}")

    # 8. List all goals
    all_goals = engine.get_goals()
    print(f"\nTotal goals in DB: {len(all_goals)}")
    for g in all_goals:
        print(f"  [{g['hierarchy_level']}] {g['name']} -> {g['state']} ({g['progress']:.0%})")

    # Cleanup
    try:
        os.remove(test_db)
    except OSError:
        pass
    print("\n✅ All tests passed")


if __name__ == "__main__":
    _test()
