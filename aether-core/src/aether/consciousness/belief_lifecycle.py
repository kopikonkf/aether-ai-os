"""
Belief Lifecycle Engine

Berdasarkan module2.txt:
"Beliefs should have a lifecycle: birth → test → revision → retirement."

Beliefs bukan statis. Mereka:
- Lahir dari evidence
- Diuji oleh pengalaman baru
- Direvisi jika evidence bertentangan
- Dipensiunkan jika terbukti salah

Setiap belief harus bisa jawab:
1. Mengapa saya percaya ini?
2. Seberapa yakin?
3. Apa yang akan mengubah pikiran saya?
"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime

from aether.paths import get_paths
DB_DIR = get_paths().db
BELIEFS_DB = DB_DIR / "decisions.db"


class BeliefLifecycle:
    """Manage beliefs through their lifecycle."""

    def __init__(self, db_path=None):
        self.db_path = str(db_path or BELIEFS_DB)
        self._init_tables()

    def _init_tables(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        # Enhanced beliefs table
        c.execute('''CREATE TABLE IF NOT EXISTS belief_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            belief_id INTEGER,
            evidence_type TEXT,
            evidence_data TEXT,
            supports BOOLEAN,
            strength REAL DEFAULT 0.5,
            timestamp TEXT,
            source TEXT DEFAULT 'experience',
            FOREIGN KEY (belief_id) REFERENCES beliefs(id)
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS belief_revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            belief_id INTEGER,
            old_confidence REAL,
            new_confidence REAL,
            reason TEXT,
            timestamp TEXT,
            FOREIGN KEY (belief_id) REFERENCES beliefs(id)
        )''')

        conn.commit()
        conn.close()

    def birth(self, claim: str, initial_confidence: float = 0.5,
              evidence: str = "", source: str = "experience") -> dict:
        """Birth a new belief from evidence."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        now = datetime.now().isoformat()

        # Check if belief already exists
        c.execute("SELECT id, confidence, evidence_count FROM beliefs WHERE claim = ?", (claim,))
        existing = c.fetchone()

        if existing:
            # Strengthen existing belief
            belief_id = existing[0]
            old_conf = existing[1]
            new_conf = min(0.95, old_conf + 0.05)
            c.execute("UPDATE beliefs SET confidence = ?, evidence_count = evidence_count + 1, updated = ? WHERE id = ?",
                     (new_conf, now, belief_id))
            c.execute("""INSERT INTO belief_evidence (belief_id, evidence_type, evidence_data, supports, strength, timestamp, source)
                        VALUES (?, 'reinforcement', ?, 1, 0.5, ?, ?)""",
                     (belief_id, evidence, now, source))
            c.execute("""INSERT INTO belief_revisions (belief_id, old_confidence, new_confidence, reason, timestamp)
                        VALUES (?, ?, ?, 'reinforced_by_new_evidence', ?)""",
                     (belief_id, old_conf, new_conf, now))
            conn.commit()
            conn.close()
            return {"belief_id": belief_id, "action": "reinforced", "old_confidence": old_conf, "new_confidence": new_conf}

        # Create new belief
        c.execute("""INSERT INTO beliefs (claim, confidence, support_strength, attack_strength, evidence_count, created, updated)
                    VALUES (?, ?, 0.5, 0.0, 1, ?, ?)""",
                 (claim, initial_confidence, now, now))
        belief_id = c.lastrowid

        # Record initial evidence
        if evidence:
            c.execute("""INSERT INTO belief_evidence (belief_id, evidence_type, evidence_data, supports, strength, timestamp, source)
                        VALUES (?, 'initial', ?, 1, ?, ?, ?)""",
                     (belief_id, evidence, initial_confidence, now, source))

        conn.commit()
        conn.close()

        return {"belief_id": belief_id, "action": "born", "confidence": initial_confidence, "claim": claim}

    def test(self, belief_id: int, new_evidence: str, supports: bool,
             evidence_strength: float = 0.5, source: str = "experience") -> dict:
        """Test a belief with new evidence."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        now = datetime.now().isoformat()

        c.execute("SELECT claim, confidence, support_strength, attack_strength, evidence_count FROM beliefs WHERE id = ?",
                 (belief_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            return {"error": "Belief not found"}

        claim, confidence, support, attack, evidence_count = row

        # Record evidence
        c.execute("""INSERT INTO belief_evidence (belief_id, evidence_type, evidence_data, supports, strength, timestamp, source)
                    VALUES (?, 'test', ?, ?, ?, ?, ?)""",
                 (belief_id, new_evidence, supports, evidence_strength, now, source))

        # Update belief
        old_confidence = confidence
        if supports:
            new_support = min(1.0, support + evidence_strength * 0.1)
            new_confidence = min(0.95, confidence + evidence_strength * 0.05)
            c.execute("UPDATE beliefs SET support_strength = ?, confidence = ?, evidence_count = evidence_count + 1, updated = ? WHERE id = ?",
                     (new_support, new_confidence, now, belief_id))
        else:
            new_attack = min(1.0, attack + evidence_strength * 0.1)
            new_confidence = max(0.05, confidence - evidence_strength * 0.1)
            c.execute("UPDATE beliefs SET attack_strength = ?, confidence = ?, evidence_count = evidence_count + 1, updated = ? WHERE id = ?",
                     (new_attack, new_confidence, now, belief_id))

        # Record revision
        c.execute("""INSERT INTO belief_revisions (belief_id, old_confidence, new_confidence, reason, timestamp)
                    VALUES (?, ?, ?, ?, ?)""",
                 (belief_id, old_confidence, new_confidence,
                  "supported" if supports else "challenged", now))

        conn.commit()
        conn.close()

        # Check if belief should be retired
        retired = False
        if new_confidence < 0.1:
            self.retire(belief_id, "confidence_below_0.1")
            retired = True

        return {
            "belief_id": belief_id,
            "claim": claim,
            "old_confidence": old_confidence,
            "new_confidence": new_confidence,
            "supports": supports,
            "retired": retired,
            "total_evidence": evidence_count + 1
        }

    def revise(self, belief_id: int, new_claim: str = None,
               new_confidence: float = None, reason: str = "manual_revision") -> dict:
        """Revise a belief."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        now = datetime.now().isoformat()

        c.execute("SELECT claim, confidence FROM beliefs WHERE id = ?", (belief_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            return {"error": "Belief not found"}

        old_claim, old_confidence = row

        if new_claim:
            c.execute("UPDATE beliefs SET claim = ?, updated = ? WHERE id = ?", (new_claim, now, belief_id))
        if new_confidence is not None:
            c.execute("UPDATE beliefs SET confidence = ?, updated = ? WHERE id = ?", (new_confidence, now, belief_id))

        c.execute("""INSERT INTO belief_revisions (belief_id, old_confidence, new_confidence, reason, timestamp)
                    VALUES (?, ?, ?, ?, ?)""",
                 (belief_id, old_confidence, new_confidence or old_confidence, reason, now))

        conn.commit()
        conn.close()

        return {"belief_id": belief_id, "old_claim": old_claim, "new_claim": new_claim or old_claim}

    def retire(self, belief_id: int, reason: str = "proven_wrong") -> dict:
        """Retire a belief."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        now = datetime.now().isoformat()

        c.execute("SELECT claim, confidence FROM beliefs WHERE id = ?", (belief_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            return {"error": "Belief not found"}

        # Set confidence to near zero (soft delete)
        c.execute("UPDATE beliefs SET confidence = 0.01, updated = ? WHERE id = ?", (now, belief_id))

        c.execute("""INSERT INTO belief_revisions (belief_id, old_confidence, new_confidence, reason, timestamp)
                    VALUES (?, ?, 0.01, ?, ?)""",
                 (belief_id, row[1], reason, now))

        conn.commit()
        conn.close()

        return {"belief_id": belief_id, "claim": row[0], "action": "retired", "reason": reason}

    def why_do_i_believe(self, belief_id: int) -> dict:
        """Answer: Mengapa saya percaya ini?"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute("SELECT claim, confidence, support_strength, attack_strength, evidence_count FROM beliefs WHERE id = ?",
                 (belief_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            return {"error": "Belief not found"}

        c.execute("SELECT evidence_type, evidence_data, supports, strength, timestamp, source FROM belief_evidence WHERE belief_id = ? ORDER BY timestamp",
                 (belief_id,))
        evidence = [{
            "type": r[0], "data": r[1], "supports": bool(r[2]),
            "strength": r[3], "timestamp": r[4], "source": r[5]
        } for r in c.fetchall()]

        c.execute("SELECT old_confidence, new_confidence, reason, timestamp FROM belief_revisions WHERE belief_id = ? ORDER BY timestamp",
                 (belief_id,))
        revisions = [{
            "old": r[0], "new": r[1], "reason": r[2], "timestamp": r[3]
        } for r in c.fetchall()]

        conn.close()

        supporting = [e for e in evidence if e["supports"]]
        opposing = [e for e in evidence if not e["supports"]]

        # What would change my mind?
        changers = []
        if row[1] > 0.7:
            changers.append(f"3+ strong contradictory evidence would reduce confidence below 0.5")
        elif row[1] > 0.3:
            changers.append(f"1 strong contradictory evidence could flip this belief")
        else:
            changers.append(f"Already low confidence — any evidence will significantly shift it")

        return {
            "claim": row[0],
            "confidence": row[1],
            "support_strength": row[2],
            "attack_strength": row[3],
            "total_evidence": row[4],
            "supporting_evidence": len(supporting),
            "opposing_evidence": len(opposing),
            "revision_history": revisions,
            "what_would_change_my_mind": changers,
            "health": "strong" if row[1] > 0.7 else "moderate" if row[1] > 0.3 else "weak"
        }

    def status(self) -> dict:
        """Get belief system status."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute("SELECT COUNT(*) FROM beliefs")
        total = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM beliefs WHERE confidence > 0.7")
        strong = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM beliefs WHERE confidence < 0.3")
        weak = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM belief_evidence")
        evidence_count = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM belief_revisions")
        revision_count = c.fetchone()[0]

        conn.close()

        return {
            "total_beliefs": total,
            "strong_beliefs": strong,
            "weak_beliefs": weak,
            "total_evidence": evidence_count,
            "total_revisions": revision_count,
            "avg_evidence_per_belief": evidence_count / max(1, total)
        }


def demo():
    """Demo belief lifecycle."""
    lifecycle = BeliefLifecycle()

    print("=" * 60)
    print("BELIEF LIFECYCLE ENGINE — DEMO")
    print("=" * 60)

    # Birth
    print("\n[1] Birth: New belief")
    result = lifecycle.birth("Price tends to reverse after liquidity sweep", 0.6,
                            evidence="Observed 3 reversals after sweeps", source="observation")
    print(f"  {result}")
    belief_id = result.get("belief_id", 1)

    # Test - supporting
    print("\n[2] Test: Supporting evidence")
    result = lifecycle.test(belief_id, "Another reversal after sweep", True, 0.7)
    print(f"  {result}")

    # Test - opposing
    print("\n[3] Test: Opposing evidence")
    result = lifecycle.test(belief_id, "Price continued after sweep this time", False, 0.5)
    print(f"  {result}")

    # Why do I believe?
    print("\n[4] Why do I believe this?")
    result = lifecycle.why_do_i_believe(belief_id)
    print(f"  Claim: {result['claim']}")
    print(f"  Confidence: {result['confidence']}")
    print(f"  Health: {result['health']}")
    print(f"  Supporting: {result['supporting_evidence']}, Opposing: {result['opposing_evidence']}")
    print(f"  What would change mind: {result['what_would_change_my_mind']}")

    # Status
    print(f"\n[5] System Status")
    print(f"  {json.dumps(lifecycle.status(), indent=2)}")


if __name__ == "__main__":
    demo()
