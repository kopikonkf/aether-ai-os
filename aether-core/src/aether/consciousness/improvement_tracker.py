"""
Self-Improvement Tracker — L10 Activation

Module ada tapi 0 tracked.
Sekarang track setiap improvement:

improvement_id
detected_gap
proposed_fix
implemented
result
success
"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime

from aether.paths import get_paths
DB_DIR = get_paths().db


class ImprovementTracker:
    """Track self-improvements with outcomes."""

    def __init__(self):
        self.decisions_db = str(DB_DIR / "decisions.db")
        self._init_tables()

    def _init_tables(self):
        conn = sqlite3.connect(self.decisions_db)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS improvements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            detected_gap TEXT NOT NULL,
            proposed_fix TEXT NOT NULL,
            implemented INTEGER DEFAULT 0,
            result TEXT,
            success INTEGER,
            impact_score REAL DEFAULT 0.0,
            module_created TEXT,
            created TEXT,
            completed TEXT
        )''')
        conn.commit()
        conn.close()

    def record(self, gap: str, fix: str, result: str = None, success: bool = None,
               impact: float = 0.0, module: str = None) -> int:
        """Record an improvement."""
        conn = sqlite3.connect(self.decisions_db)
        c = conn.cursor()
        now = datetime.now().isoformat()
        c.execute('''INSERT INTO improvements
                    (detected_gap, proposed_fix, implemented, result, success, impact_score, module_created, created, completed)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                 (gap, fix, 1 if result else 0, result, 1 if success else (0 if success is not None else None),
                  impact, module, now, now if result else None))
        imp_id = c.lastrowid
        conn.commit()
        conn.close()
        return imp_id

    def complete(self, imp_id: int, result: str, success: bool, impact: float = 0.0):
        """Mark improvement as completed."""
        conn = sqlite3.connect(self.decisions_db)
        c = conn.cursor()
        now = datetime.now().isoformat()
        c.execute('''UPDATE improvements SET result=?, success=?, impact_score=?,
                    implemented=1, completed=? WHERE id=?''',
                 (result, 1 if success else 0, impact, now, imp_id))
        conn.commit()
        conn.close()

    def get_all(self) -> list:
        """Get all improvements."""
        conn = sqlite3.connect(self.decisions_db)
        c = conn.cursor()
        rows = c.execute(
            "SELECT id, detected_gap, proposed_fix, implemented, result, success, impact_score, module_created, created FROM improvements ORDER BY id"
        ).fetchall()
        conn.close()
        return [{"id": r[0], "gap": r[1], "fix": r[2], "implemented": r[3],
                "result": r[4], "success": r[5], "impact": r[6],
                "module": r[7], "created": r[8]} for r in rows]

    def seed_from_history(self) -> int:
        """Seed improvements from known history."""
        known_improvements = [
            {
                "gap": "Phantom evidence — beliefs with evidence_count > 0 but 0 actual rows",
                "fix": "belief_audit.py — sync evidence_count to actual rows",
                "result": "5 unsupported beliefs discovered, evidence_count corrected",
                "success": True, "impact": 0.9, "module": "belief_audit.py"
            },
            {
                "gap": "No belief lifecycle — beliefs born but never reviewed",
                "fix": "belief_lifecycle.py — PROPOSED/ACTIVE/CHALLENGED/VALIDATED/RETIRED",
                "result": "Belief #5 challenged, lifecycle columns added",
                "success": True, "impact": 0.85, "module": "belief_lifecycle.py"
            },
            {
                "gap": "No concept provenance — concepts without origin",
                "fix": "provenance.py — track experience→concept links",
                "result": "0/10 concepts traceable (gap identified, pipeline active)",
                "success": True, "impact": 0.8, "module": "provenance.py"
            },
            {
                "gap": "No prediction engine — beliefs never tested",
                "fix": "prediction_engine.py — force beliefs to predict",
                "result": "6 predictions generated for all dormant beliefs",
                "success": True, "impact": 0.8, "module": "prediction_engine.py"
            },
            {
                "gap": "No dead knowledge detection — unused concepts accumulating",
                "fix": "dead_knowledge.py — detect dormant concepts/beliefs/patterns",
                "result": "9 dormant concepts detected",
                "success": True, "impact": 0.7, "module": "dead_knowledge.py"
            },
            {
                "gap": "No generalization pipeline — experiences not becoming knowledge",
                "fix": "generalization.py — Experience→Pattern→Concept pipeline",
                "result": "12 exp→10 concepts, Knowledge Yield trackable",
                "success": True, "impact": 0.85, "module": "generalization.py"
            },
            {
                "gap": "No idle consolidation — memory grows without compression",
                "fix": "idle_consolidation.py — 5-step idle cycle",
                "result": "Full cycle working: consolidation→generalization→belief_review→compress→dream",
                "success": True, "impact": 0.75, "module": "idle_consolidation.py"
            },
            {
                "gap": "Dashboard metric 4 inflated — concept_formation showed 100%",
                "fix": "Fixed scoring to use actual concept_formation.py tables",
                "result": "Score corrected from 100% to 37.5%",
                "success": True, "impact": 0.6, "module": "dashboard.py"
            },
            {
                "gap": "No self-model traits — 0 identity entries",
                "fix": "self_model_builder.py — extract traits from behavior",
                "result": "9 traits extracted from behavior patterns",
                "success": True, "impact": 0.8, "module": "self_model_builder.py"
            },
            {
                "gap": "No trace graph — experiences not connected to beliefs",
                "fix": "trace_graph.py — Experience→Concept→Belief→Prediction edges",
                "result": "10 edges built, connectivity report active",
                "success": True, "impact": 0.75, "module": "trace_graph.py"
            },
            {
                "gap": "No curiosity queue — no gap detection",
                "fix": "curiosity_engine.py — gap-driven curiosity",
                "result": "Auto-detect knowledge gaps, prioritize by uncertainty×impact",
                "success": True, "impact": 0.7, "module": "curiosity_engine.py"
            },
        ]

        count = 0
        for imp in known_improvements:
            self.record(
                gap=imp["gap"], fix=imp["fix"], result=imp["result"],
                success=imp["success"], impact=imp["impact"], module=imp["module"]
            )
            count += 1

        return count

    def report(self) -> str:
        """Human-readable report."""
        all_imps = self.get_all()
        lines = ["=" * 55]
        lines.append("  SELF-IMPROVEMENT TRACKER (L10)")
        lines.append("=" * 55)
        lines.append(f"  Total: {len(all_imps)} improvements tracked")
        lines.append("")

        success_count = sum(1 for i in all_imps if i["success"] == 1)
        total_impact = sum(i["impact"] for i in all_imps if i["impact"])

        for imp in all_imps:
            emoji = "✅" if imp["success"] == 1 else "❌" if imp["success"] == 0 else "⏳"
            lines.append(f"  {emoji} #{imp['id']}: {imp['gap'][:60]}")
            lines.append(f"     Fix: {imp['fix'][:50]}")
            if imp["result"]:
                lines.append(f"     Result: {imp['result'][:50]}")
            lines.append(f"     Impact: {imp['impact']:.1f} | Module: {imp.get('module', 'N/A')}")

        lines.append("")
        lines.append(f"  Success Rate: {success_count}/{len(all_imps)} ({success_count/max(len(all_imps),1)*100:.0f}%)")
        lines.append(f"  Total Impact: {total_impact:.1f}")
        lines.append("=" * 55)
        return "\n".join(lines)


def demo():
    tracker = ImprovementTracker()

    # Seed from history
    existing = tracker.get_all()
    if len(existing) == 0:
        count = tracker.seed_from_history()
        print(f"Seeded {count} improvements from history\n")

    print(tracker.report())


if __name__ == "__main__":
    demo()
