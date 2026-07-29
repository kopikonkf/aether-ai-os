"""
Curiosity Queue — L6 Activation

Gap-driven curiosity, bukan random exploration.

unknowns:
  - why live_wr < backtest_wr
  - why belief_4 no evidence
  - why concept_reuse low

Formula:
  high uncertainty + high impact = high curiosity
"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime

from aether.paths import get_paths
DB_DIR = get_paths().db


class CuriosityEngine:
    """Gap-driven curiosity queue."""

    def __init__(self):
        self.consciousness_db = str(DB_DIR / "consciousness.db")
        self.decisions_db = str(DB_DIR / "decisions.db")
        self.world_db = str(DB_DIR / "world_model.db")
        self._init_tables()

    def _init_tables(self):
        conn = sqlite3.connect(self.decisions_db)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS curiosity_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            gap_type TEXT,
            uncertainty REAL DEFAULT 0.5,
            impact REAL DEFAULT 0.5,
            curiosity_score REAL DEFAULT 0.5,
            status TEXT DEFAULT 'open',
            answer TEXT,
            created TEXT,
            resolved TEXT
        )''')
        conn.commit()
        conn.close()

    def detect_gaps(self) -> list:
        """Auto-detect knowledge gaps."""
        gaps = []

        # Gap 1: Beliefs without evidence
        conn = sqlite3.connect(self.decisions_db)
        c = conn.cursor()
        try:
            no_ev = c.execute(
                "SELECT id, claim FROM beliefs WHERE id NOT IN (SELECT DISTINCT belief_id FROM belief_evidence)"
            ).fetchall()
            for bid, claim in no_ev:
                gaps.append({
                    "question": f"Why does belief #{bid} ('{claim[:40]}') have no evidence?",
                    "gap_type": "no_evidence",
                    "uncertainty": 0.9,
                    "impact": 0.7
                })
        except:
            pass

        # Gap 2: Overconfident beliefs
        try:
            overconf = c.execute(
                "SELECT id, claim, confidence FROM beliefs WHERE confidence > 0.6 AND id NOT IN (SELECT DISTINCT belief_id FROM belief_evidence)"
            ).fetchall()
            for bid, claim, conf in overconf:
                gaps.append({
                    "question": f"Is belief #{bid} ('{claim[:40]}') overconfident? conf={conf}, ev=0",
                    "gap_type": "overconfident",
                    "uncertainty": 0.85,
                    "impact": 0.8
                })
        except:
            pass

        # Gap 3: Concepts without provenance
        try:
            conn2 = sqlite3.connect(self.consciousness_db)
            c2 = conn2.cursor()
            concepts = c2.execute("SELECT id, name FROM concepts").fetchall()
            for cid, name in concepts:
                try:
                    prov = c2.execute(
                        "SELECT COUNT(*) FROM concept_provenance WHERE concept_id=?", (cid,)
                    ).fetchone()[0]
                    if prov == 0:
                        gaps.append({
                            "question": f"Where does concept '{name}' come from? (no provenance)",
                            "gap_type": "no_provenance",
                            "uncertainty": 0.8,
                            "impact": 0.6
                        })
                except:
                    pass
            conn2.close()
        except:
            pass

        # Gap 4: Predictions never evaluated
        try:
            stale = c.execute(
                "SELECT COUNT(*) FROM predictions WHERE status='pending'"
            ).fetchone()[0]
            if stale > 0:
                gaps.append({
                    "question": f"{stale} predictions pending — what happened?",
                    "gap_type": "unevaluated",
                    "uncertainty": 0.7,
                    "impact": 0.9
                })
        except:
            pass

        # Gap 5: Live vs Backtest gap
        gaps.append({
            "question": "Why is live WR (39.69%) so different from backtest WR (89.6%)?",
            "gap_type": "performance_gap",
            "uncertainty": 0.95,
            "impact": 0.95
        })

        conn.close()
        return gaps

    def enqueue(self, question: str, gap_type: str, uncertainty: float, impact: float):
        """Add item to curiosity queue."""
        score = (uncertainty + impact) / 2
        conn = sqlite3.connect(self.decisions_db)
        c = conn.cursor()
        now = datetime.now().isoformat()
        # Deduplicate
        existing = c.execute(
            "SELECT id FROM curiosity_queue WHERE question=? AND status='open'", (question,)
        ).fetchone()
        if not existing:
            c.execute('''INSERT INTO curiosity_queue
                        (question, gap_type, uncertainty, impact, curiosity_score, status, created)
                        VALUES (?, ?, ?, ?, ?, 'open', ?)''',
                     (question, gap_type, uncertainty, impact, score, now))
        conn.commit()
        conn.close()

    def auto_enqueue_gaps(self) -> int:
        """Detect and enqueue all gaps."""
        gaps = self.detect_gaps()
        for g in gaps:
            self.enqueue(g["question"], g["gap_type"], g["uncertainty"], g["impact"])
        return len(gaps)

    def get_queue(self, limit: int = 10) -> list:
        """Get top curiosity items sorted by score."""
        conn = sqlite3.connect(self.decisions_db)
        c = conn.cursor()
        rows = c.execute(
            "SELECT id, question, gap_type, curiosity_score, status FROM curiosity_queue ORDER BY curiosity_score DESC LIMIT ?",
            (limit,)
        ).fetchall()
        conn.close()
        return [{"id": r[0], "question": r[1], "gap_type": r[2],
                "score": r[3], "status": r[4]} for r in rows]

    def resolve(self, item_id: int, answer: str):
        """Mark curiosity item as resolved."""
        conn = sqlite3.connect(self.decisions_db)
        c = conn.cursor()
        now = datetime.now().isoformat()
        c.execute("UPDATE curiosity_queue SET status='resolved', answer=?, resolved=? WHERE id=?",
                 (answer, now, item_id))
        conn.commit()
        conn.close()

    def status(self) -> dict:
        """Queue status."""
        conn = sqlite3.connect(self.decisions_db)
        c = conn.cursor()
        try:
            total = c.execute("SELECT COUNT(*) FROM curiosity_queue").fetchone()[0]
            open_q = c.execute("SELECT COUNT(*) FROM curiosity_queue WHERE status='open'").fetchone()[0]
            resolved = c.execute("SELECT COUNT(*) FROM curiosity_queue WHERE status='resolved'").fetchone()[0]
        except:
            total = open_q = resolved = 0
        conn.close()
        return {"total": total, "open": open_q, "resolved": resolved}


def demo():
    engine = CuriosityEngine()
    print("=== Curiosity Engine (L6) ===\n")

    # Auto-detect and enqueue
    added = engine.auto_enqueue_gaps()
    print(f"Gaps detected and enqueued: {added}")

    # Show queue
    queue = engine.get_queue()
    print(f"\nTop {len(queue)} curiosity items:")
    for item in queue:
        bar_len = int(item["score"] * 10)
        bar = "█" * bar_len + "░" * (10 - bar_len)
        print(f"  [{bar}] {item['score']:.2f} [{item['gap_type']}]")
        print(f"    {item['question'][:70]}")

    # Status
    s = engine.status()
    print(f"\nQueue: {s['total']} total, {s['open']} open, {s['resolved']} resolved")


if __name__ == "__main__":
    demo()
