"""
Belief Integrity Audit — Sprint #2.5

Jawab 5 pertanyaan kritis:
1. Belief mana yang tidak punya evidence?
2. Belief mana yang paling banyak ditentang?
3. Belief mana yang belum diuji 30 hari?
4. Belief mana yang berubah paling sering?
5. Belief mana yang paling berpengaruh ke keputusan trading?

Status lifecycle:
  PROPOSED → ACTIVE → CHALLENGED → VALIDATED → RETIRED

Validity Domain:
  Belief tidak boleh global. Harus specify valid_for.

Rule:
  No trace = No evidence
  evidence_count > 0 BUT actual_evidence_rows = 0 → RED FLAG
"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime, timedelta

from aether.paths import get_paths
DB_DIR = get_paths().db


class BeliefAuditor:
    """Audit and manage belief integrity."""

    def __init__(self, db_path: str = None):
        self.db_path = str(db_path or DB_DIR / "decisions.db")

    def _conn(self):
        return sqlite3.connect(self.db_path)

    # ── AUDIT QUERIES ──────────────────────────────────────────

    def audit_1_no_evidence(self) -> list:
        """Beliefs with evidence_count > 0 but 0 actual evidence rows."""
        conn = self._conn()
        c = conn.cursor()

        beliefs = c.execute('SELECT id, claim, confidence, evidence_count, status FROM beliefs').fetchall()
        ev_counts = {r[0]: r[1] for r in c.execute(
            'SELECT belief_id, COUNT(*) FROM belief_evidence GROUP BY belief_id').fetchall()}

        results = []
        for bid, claim, conf, stored_ev, status in beliefs:
            actual = ev_counts.get(bid, 0)
            if actual == 0:
                flag = "🔴 RED FLAG" if stored_ev > 0 else "⚪ no evidence"
                results.append({
                    "id": bid, "claim": claim, "confidence": conf,
                    "stored_evidence": stored_ev, "actual_evidence": actual,
                    "status": status, "flag": flag
                })
        conn.close()
        return results

    def audit_2_most_challenged(self) -> list:
        """Beliefs with most contradictions or revisions."""
        conn = self._conn()
        c = conn.cursor()

        # From belief_revisions
        revisions = c.execute(
            'SELECT belief_id, COUNT(*) as cnt FROM belief_revisions GROUP BY belief_id ORDER BY cnt DESC'
        ).fetchall()

        results = []
        for bid, cnt in revisions:
            row = c.execute('SELECT claim, confidence, attack_strength FROM beliefs WHERE id=?', (bid,)).fetchone()
            if row:
                results.append({
                    "id": bid, "claim": row[0], "confidence": row[1],
                    "revisions": cnt, "attack_strength": row[2]
                })

        # From doubted_beliefs in consciousness.db
        try:
            conn2 = sqlite3.connect(str(DB_DIR / "consciousness.db"))
            doubted = conn2.execute(
                'SELECT claim, doubt, contradiction_count FROM doubted_beliefs ORDER BY doubt DESC LIMIT 5'
            ).fetchall()
            for claim, doubt, contra in doubted:
                results.append({
                    "id": "doubted", "claim": claim, "doubt_score": doubt,
                    "contradictions": contra
                })
            conn2.close()
        except:
            pass

        conn.close()
        return results

    def audit_3_untested_30_days(self) -> list:
        """Beliefs not tested in last 30 days."""
        conn = self._conn()
        c = conn.cursor()

        threshold = (datetime.now() - timedelta(days=30)).isoformat()
        beliefs = c.execute(
            'SELECT id, claim, confidence, created, updated, status FROM beliefs'
        ).fetchall()

        ev_dates = {}
        for row in c.execute('SELECT belief_id, MAX(timestamp) FROM belief_evidence GROUP BY belief_id').fetchall():
            ev_dates[row[0]] = row[1]

        rev_dates = {}
        for row in c.execute('SELECT belief_id, MAX(timestamp) FROM belief_revisions GROUP BY belief_id').fetchall():
            rev_dates[row[0]] = row[1]

        results = []
        for bid, claim, conf, created, updated, status in beliefs:
            last_activity = ev_dates.get(bid) or rev_dates.get(bid) or updated or created
            if last_activity and last_activity < threshold:
                results.append({
                    "id": bid, "claim": claim, "confidence": conf,
                    "status": status, "last_activity": last_activity,
                    "days_stale": (datetime.now() - datetime.fromisoformat(last_activity)).days
                })
        conn.close()
        return results

    def audit_4_most_changed(self) -> list:
        """Beliefs that changed most often."""
        conn = self._conn()
        c = conn.cursor()

        revisions = c.execute('''
            SELECT belief_id, COUNT(*) as cnt, 
                   MIN(old_confidence), MAX(new_confidence),
                   GROUP_CONCAT(reason)
            FROM belief_revisions 
            GROUP BY belief_id 
            ORDER BY cnt DESC
        ''').fetchall()

        results = []
        for bid, cnt, min_conf, max_conf, reasons in revisions:
            claim = c.execute('SELECT claim FROM beliefs WHERE id=?', (bid,)).fetchone()
            if claim:
                results.append({
                    "id": bid, "claim": claim[0], "revision_count": cnt,
                    "confidence_range": f"{min_conf:.2f} → {max_conf:.2f}",
                    "volatility": abs(max_conf - min_conf) if min_conf and max_conf else 0
                })
        conn.close()
        return results

    def audit_5_trading_impact(self) -> list:
        """Beliefs most impactful to trading decisions.
        
        Proxy: beliefs with highest confidence × evidence count.
        """
        conn = self._conn()
        c = conn.cursor()

        beliefs = c.execute('''
            SELECT id, claim, confidence, evidence_count, status, valid_for
            FROM beliefs ORDER BY confidence DESC
        ''').fetchall()

        ev_counts = {r[0]: r[1] for r in c.execute(
            'SELECT belief_id, COUNT(*) FROM belief_evidence GROUP BY belief_id').fetchall()}

        results = []
        for bid, claim, conf, stored_ev, status, valid_for in beliefs:
            actual_ev = ev_counts.get(bid, 0)
            impact = conf * max(actual_ev, 1)
            results.append({
                "id": bid, "claim": claim, "confidence": conf,
                "actual_evidence": actual_ev, "impact_score": round(impact, 2),
                "status": status, "valid_for": valid_for
            })

        results.sort(key=lambda x: x["impact_score"], reverse=True)
        conn.close()
        return results

    # ── BELIEF LIFECYCLE ───────────────────────────────────────

    def propose(self, claim: str, confidence: float = 0.5,
                valid_for: str = "XAUUSD,M15") -> dict:
        """Propose a new belief (not yet active)."""
        conn = self._conn()
        c = conn.cursor()
        now = datetime.now().isoformat()
        next_week = (datetime.now() + timedelta(days=7)).isoformat()

        c.execute('''INSERT INTO beliefs 
                    (claim, confidence, support_strength, attack_strength, evidence_count,
                     created, updated, status, valid_for, next_review)
                    VALUES (?, ?, 0, 0, 0, ?, ?, 'PROPOSED', ?, ?)''',
                 (claim, confidence, now, now, valid_for, next_week))
        bid = c.lastrowid
        conn.commit()
        conn.close()
        return {"belief_id": bid, "status": "PROPOSED", "next_review": next_week}

    def activate(self, belief_id: int) -> dict:
        """Move belief from PROPOSED to ACTIVE."""
        conn = self._conn()
        c = conn.cursor()
        c.execute("UPDATE beliefs SET status='ACTIVE', updated=? WHERE id=? AND status='PROPOSED'",
                 (datetime.now().isoformat(), belief_id))
        changed = c.rowcount
        conn.commit()
        conn.close()
        return {"belief_id": belief_id, "status": "ACTIVE" if changed else "not_found_or_wrong_status"}

    def challenge(self, belief_id: int, reason: str,
                  required_evidence: int = 20) -> dict:
        """Challenge a belief — not retired, just questioned."""
        conn = self._conn()
        c = conn.cursor()
        now = datetime.now().isoformat()
        next_review = (datetime.now() + timedelta(days=7)).isoformat()

        c.execute('''UPDATE beliefs SET status='CHALLENGED', last_challenged=?, 
                    challenge_reason=?, required_evidence=?, next_review=?, updated=?
                    WHERE id=?''',
                 (now, reason, required_evidence, next_review, now, belief_id))
        changed = c.rowcount
        conn.commit()
        conn.close()
        return {"belief_id": belief_id, "status": "CHALLENGED" if changed else "not_found",
                "required_evidence": required_evidence, "next_review": next_review}

    def validate(self, belief_id: int) -> dict:
        """Mark belief as validated — has enough real evidence."""
        conn = self._conn()
        c = conn.cursor()

        # Check actual evidence
        actual = c.execute('SELECT COUNT(*) FROM belief_evidence WHERE belief_id=?',
                          (belief_id,)).fetchone()[0]
        required = c.execute('SELECT required_evidence FROM beliefs WHERE id=?',
                            (belief_id,)).fetchone()[0] or 5

        if actual < required:
            conn.close()
            return {"belief_id": belief_id, "status": "insufficient_evidence",
                    "actual": actual, "required": required}

        c.execute("UPDATE beliefs SET status='VALIDATED', updated=? WHERE id=?",
                 (datetime.now().isoformat(), belief_id))
        conn.commit()
        conn.close()
        return {"belief_id": belief_id, "status": "VALIDATED", "evidence": actual}

    def retire(self, belief_id: int, reason: str) -> dict:
        """Retire a belief — no longer active."""
        conn = self._conn()
        c = conn.cursor()
        c.execute("UPDATE beliefs SET status='RETIRED', challenge_reason=?, updated=? WHERE id=?",
                 (reason, datetime.now().isoformat(), belief_id))
        changed = c.rowcount
        conn.commit()
        conn.close()
        return {"belief_id": belief_id, "status": "RETIRED" if changed else "not_found"}

    def add_evidence(self, belief_id: int, evidence_type: str,
                     evidence_data: str, supports: bool,
                     strength: float = 0.5, source: str = "experience") -> dict:
        """Add REAL traceable evidence to a belief."""
        conn = self._conn()
        c = conn.cursor()
        now = datetime.now().isoformat()

        c.execute('''INSERT INTO belief_evidence 
                    (belief_id, evidence_type, evidence_data, supports, strength, timestamp, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?)''',
                 (belief_id, evidence_type, evidence_data, 1 if supports else 0,
                  strength, now, source))

        # Update belief's support/attack strength
        if supports:
            c.execute('''UPDATE beliefs SET support_strength = support_strength + ?,
                        evidence_count = evidence_count + 1, updated=? WHERE id=?''',
                     (strength * 0.1, now, belief_id))
        else:
            c.execute('''UPDATE beliefs SET attack_strength = attack_strength + ?,
                        evidence_count = evidence_count + 1, updated=? WHERE id=?''',
                     (strength * 0.1, now, belief_id))

        # Record revision
        old_conf = c.execute('SELECT confidence FROM beliefs WHERE id=?', (belief_id,)).fetchone()
        if old_conf:
            delta = strength * 0.1 if supports else -strength * 0.1
            new_conf = max(0.0, min(1.0, old_conf[0] + delta))
            c.execute("UPDATE beliefs SET confidence=? WHERE id=?", (new_conf, belief_id))
            c.execute('''INSERT INTO belief_revisions (belief_id, old_confidence, new_confidence, reason, timestamp)
                        VALUES (?, ?, ?, ?, ?)''',
                     (belief_id, old_conf[0], new_conf,
                      "supported" if supports else "challenged", now))

        conn.commit()
        conn.close()
        return {"belief_id": belief_id, "evidence_type": evidence_type,
                "supports": supports, "strength": strength}

    # ── FULL AUDIT REPORT ──────────────────────────────────────

    def full_audit(self) -> dict:
        """Run all 5 audits and return report."""
        return {
            "timestamp": datetime.now().isoformat(),
            "audit_1_no_evidence": self.audit_1_no_evidence(),
            "audit_2_most_challenged": self.audit_2_most_challenged(),
            "audit_3_untested_30_days": self.audit_3_untested_30_days(),
            "audit_4_most_changed": self.audit_4_most_changed(),
            "audit_5_trading_impact": self.audit_5_trading_impact()
        }


def demo():
    auditor = BeliefAuditor()
    print("=== Belief Integrity Audit ===\n")

    # Audit 1
    no_ev = auditor.audit_1_no_evidence()
    print(f"1. BELIEFS WITHOUT EVIDENCE: {len(no_ev)}")
    for b in no_ev:
        print(f"   {b['flag']} #{b['id']}: {b['claim'][:50]} (stored={b['stored_evidence']}, actual={b['actual_evidence']})")

    # Audit 2
    challenged = auditor.audit_2_most_challenged()
    print(f"\n2. MOST CHALLENGED: {len(challenged)}")
    for b in challenged[:3]:
        print(f"   #{b.get('id')}: {b['claim'][:50]}")

    # Audit 3
    stale = auditor.audit_3_untested_30_days()
    print(f"\n3. UNTESTED 30+ DAYS: {len(stale)}")
    for b in stale:
        print(f"   #{b['id']}: {b['claim'][:50]} (stale {b['days_stale']}d)")

    # Audit 4
    volatile = auditor.audit_4_most_changed()
    print(f"\n4. MOST CHANGED: {len(volatile)}")
    for b in volatile[:3]:
        print(f"   #{b['id']}: {b['claim'][:50]} ({b['revision_count']} revisions)")

    # Audit 5
    impact = auditor.audit_5_trading_impact()
    print(f"\n5. TRADING IMPACT (top 3):")
    for b in impact[:3]:
        print(f"   #{b['id']}: {b['claim'][:50]} (impact={b['impact_score']}, ev={b['actual_evidence']})")


if __name__ == "__main__":
    demo()
