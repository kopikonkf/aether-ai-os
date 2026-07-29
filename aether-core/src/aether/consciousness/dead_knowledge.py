"""
Dead Knowledge Detector — Deliverable 5, Sprint #3

Cari:
  - Concepts never used
  - Beliefs never tested
  - Predictions never evaluated

Tandai: status = 'dormant'

Sistem belajar yang sehat harus bisa membuang pengetahuan yang tidak berguna.
"""
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

from aether.paths import get_paths
DB_DIR = get_paths().db


class DeadKnowledgeDetector:
    """Find unused, untested, dormant knowledge."""

    def __init__(self):
        self.consciousness_db = str(DB_DIR / "consciousness.db")
        self.decisions_db = str(DB_DIR / "decisions.db")

    def full_audit(self) -> dict:
        """Complete dead knowledge audit."""
        return {
            "timestamp": datetime.now().isoformat(),
            "dormant_concepts": self._find_dormant_concepts(),
            "dormant_beliefs": self._find_dormant_beliefs(),
            "stale_predictions": self._find_stale_predictions(),
            "unused_patterns": self._find_unused_patterns(),
            "summary": {}
        }

    def _find_dormant_concepts(self) -> list:
        """Concepts never referenced by beliefs, predictions, or other concepts."""
        conn = sqlite3.connect(self.consciousness_db)
        c = conn.cursor()

        concepts = c.execute(
            "SELECT id, name, confidence, status, created FROM concepts"
        ).fetchall()

        dormant = []
        for cid, name, conf, status, created in concepts:
            # Check if concept is referenced in concept_provenance
            try:
                prov_count = c.execute(
                    "SELECT COUNT(*) FROM concept_provenance WHERE concept_id=?", (cid,)
                ).fetchone()[0]
            except:
                prov_count = 0

            # Check if concept has conditions
            try:
                cond_count = c.execute(
                    "SELECT COUNT(*) FROM concept_conditions WHERE concept_id=?", (cid,)
                ).fetchone()[0]
            except:
                cond_count = 0

            # Check if concept name appears in belief claims
            decisions_conn = sqlite3.connect(self.decisions_db)
            dc = decisions_conn.cursor()
            belief_refs = dc.execute(
                "SELECT COUNT(*) FROM beliefs WHERE claim LIKE ?",
                (f"%{name.lower()}%",)
            ).fetchone()[0]
            decisions_conn.close()

            # Dormant if: no provenance, no conditions, no belief references
            if prov_count == 0 and cond_count == 0 and belief_refs == 0:
                age_days = 0
                if created:
                    try:
                        created_dt = datetime.fromisoformat(created)
                        age_days = (datetime.now() - created_dt).days
                    except:
                        pass

                dormant.append({
                    "id": cid, "name": name, "confidence": conf,
                    "status": status, "age_days": age_days,
                    "reason": "no_provenance,no_conditions,no_belief_refs"
                })

        conn.close()
        return dormant

    def _find_dormant_beliefs(self) -> list:
        """Beliefs never tested (no predictions, no evidence)."""
        conn = sqlite3.connect(self.decisions_db)
        c = conn.cursor()

        beliefs = c.execute(
            "SELECT id, claim, confidence, status, created FROM beliefs"
        ).fetchall()

        dormant = []
        for bid, claim, conf, status, created in beliefs:
            # Count predictions
            pred_count = c.execute(
                "SELECT COUNT(*) FROM predictions WHERE belief_id=?", (bid,)
            ).fetchone()[0]

            # Count evidence
            ev_count = c.execute(
                "SELECT COUNT(*) FROM belief_evidence WHERE belief_id=?", (bid,)
            ).fetchone()[0]

            if pred_count == 0 and ev_count == 0:
                dormant.append({
                    "id": bid, "claim": claim, "confidence": conf,
                    "status": status, "predictions": pred_count,
                    "evidence": ev_count,
                    "reason": "no_predictions,no_evidence"
                })

        conn.close()
        return dormant

    def _find_stale_predictions(self) -> list:
        """Predictions pending > 7 days."""
        conn = sqlite3.connect(self.decisions_db)
        c = conn.cursor()

        cutoff = (datetime.now() - timedelta(days=7)).isoformat()
        stale = c.execute(
            "SELECT id, belief_id, prediction_text, created FROM predictions WHERE status='pending' AND created < ?",
            (cutoff,)
        ).fetchall()

        conn.close()
        return [{"id": r[0], "belief_id": r[1], "prediction": r[2], "created": r[3]}
                for r in stale]

    def _find_unused_patterns(self) -> list:
        """Patterns that never graduated to concepts."""
        conn = sqlite3.connect(self.consciousness_db)
        c = conn.cursor()

        try:
            patterns = c.execute(
                "SELECT id, name, strength, created FROM patterns"
            ).fetchall()

            unused = []
            for pid, name, strength, created in patterns:
                # Check if pattern is linked to any concept
                concept_ref = c.execute(
                    "SELECT COUNT(*) FROM concepts WHERE pattern_ids LIKE ?",
                    (f"%{pid}%",)
                ).fetchone()[0]

                if concept_ref == 0:
                    unused.append({
                        "id": pid, "name": name, "strength": strength,
                        "reason": "never_graduated_to_concept"
                    })

            conn.close()
            return unused
        except:
            conn.close()
            return []

    def mark_dormant(self, table: str, item_id: int, reason: str):
        """Mark an item as dormant."""
        conn = sqlite3.connect(
            self.consciousness_db if table in ("concepts", "patterns") else self.decisions_db
        )
        c = conn.cursor()
        try:
            c.execute(f"UPDATE {table} SET status='dormant' WHERE id=?", (item_id,))
            conn.commit()
        except:
            pass
        conn.close()

    def summary(self, audit: dict) -> str:
        """Human-readable summary."""
        lines = ["=== Dead Knowledge Audit ==="]
        dc = audit["dormant_concepts"]
        db = audit["dormant_beliefs"]
        sp = audit["stale_predictions"]
        up = audit["unused_patterns"]

        lines.append(f"  Dormant concepts: {len(dc)}")
        lines.append(f"  Dormant beliefs: {len(db)}")
        lines.append(f"  Stale predictions: {len(sp)}")
        lines.append(f"  Unused patterns: {len(up)}")

        if dc:
            lines.append(f"\n  Dormant Concepts:")
            for c in dc[:5]:
                lines.append(f"    #{c['id']}: {c['name']} — {c['reason']}")

        if db:
            lines.append(f"\n  Dormant Beliefs:")
            for b in db[:5]:
                lines.append(f"    #{b['id']}: {b['claim'][:50]} — {b['reason']}")

        return "\n".join(lines)


def demo():
    detector = DeadKnowledgeDetector()
    print("=== Dead Knowledge Detector ===\n")

    audit = detector.full_audit()
    print(detector.summary(audit))


if __name__ == "__main__":
    demo()
