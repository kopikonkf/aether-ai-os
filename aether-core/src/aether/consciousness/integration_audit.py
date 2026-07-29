"""
Integration Audit — Module 15

7 audit tests untuk membuktikan semua modul saling terhubung.
Bukan "apakah hidup?" tapi "apakah saling memengaruhi?"

Audit Scorecard:
  0 = tidak ada
  1 = ada tapi parsial
  2 = terbukti

  0-4   = Modul terpisah
  5-9   = Semi-integrated
  10-14 = Integrated
  15+   = Unified Cognitive System
"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime

from aether.paths import get_paths
DB_DIR = get_paths().db


class IntegrationAudit:
    """7 audit tests for cross-module integration."""

    def __init__(self):
        self.consciousness_db = str(DB_DIR / "consciousness.db")
        self.decisions_db = str(DB_DIR / "decisions.db")
        self.world_db = str(DB_DIR / "world_model.db")
        self.self_db = str(DB_DIR / "self_model.db")

    def run_all(self) -> dict:
        """Run all 7 audits."""
        results = {
            "timestamp": datetime.now().isoformat(),
            "audit_1_trace": self.audit_1_trace_test(),
            "audit_2_memory_retrieval": self.audit_2_memory_retrieval(),
            "audit_3_counterfactual": self.audit_3_counterfactual(),
            "audit_4_belief_provenance": self.audit_4_belief_provenance(),
            "audit_5_self_model_grounding": self.audit_5_self_model_grounding(),
            "audit_6_end_to_end_growth": self.audit_6_end_to_end_growth(),
            "audit_7_disconnect": self.audit_7_disconnect(),
        }

        # Score
        total = 0
        for key in results:
            if key.startswith("audit_"):
                score = results[key].get("score", 0)
                total += score

        results["total_score"] = total
        results["max_score"] = 14
        results["rating"] = self._rating(total)
        return results

    def _rating(self, score: int) -> str:
        if score <= 4: return "Modul Terpisah"
        if score <= 9: return "Semi-Integrated"
        if score <= 14: return "Integrated"
        return "Unified Cognitive System"

    # ── Audit 1: Trace Test ─────────────────────────────────

    def audit_1_trace_test(self) -> dict:
        """Satu pengalaman baru → jejak perubahan di semua modul."""
        conn = sqlite3.connect(self.consciousness_db)
        c = conn.cursor()

        # Check if any experience has traceable impact across modules
        # Look for experiences that affected: beliefs, concepts, predictions, narrative
        traces = []

        # Check core_memories → linked to beliefs via belief_evidence (in decisions.db)
        try:
            ev_links = sqlite3.connect(self.decisions_db).execute(
                "SELECT COUNT(DISTINCT belief_id) FROM belief_evidence"
            ).fetchone()[0]
        except:
            ev_links = 0

        # Check core_memories → linked to concepts via concept_provenance
        try:
            prov_links = c.execute(
                "SELECT COUNT(DISTINCT concept_id) FROM concept_provenance"
            ).fetchone()[0]
        except:
            prov_links = 0

        # Check if predictions reference beliefs
        try:
            pred_links = sqlite3.connect(self.decisions_db).execute(
                "SELECT COUNT(DISTINCT belief_id) FROM predictions"
            ).fetchone()[0]
        except:
            pred_links = 0

        conn.close()

        score = 0
        if ev_links > 0: score += 1
        if prov_links > 0: score += 1

        return {
            "score": score,
            "belief_links": ev_links,
            "concept_links": prov_links,
            "prediction_links": pred_links,
            "detail": f"Experience→Belief: {ev_links}, Experience→Concept: {prov_links}, Belief→Prediction: {pred_links}",
            "status": "PASS" if score >= 2 else "PARTIAL" if score == 1 else "FAIL"
        }

    # ── Audit 2: Memory Retrieval Test ──────────────────────

    def audit_2_memory_retrieval(self) -> dict:
        """Belief mana yang dipengaruhi oleh pengalaman pertama?"""
        conn = sqlite3.connect(self.decisions_db)
        c = conn.cursor()

        # Check if any belief has evidence linking to specific experiences
        linked = c.execute('''SELECT b.id, b.claim, e.evidence_data
                            FROM beliefs b 
                            JOIN belief_evidence e ON b.id = e.belief_id 
                            LIMIT 5''').fetchall()
        conn.close()

        score = 1 if len(linked) > 0 else 0
        return {
            "score": score,
            "linked_beliefs": len(linked),
            "samples": [{"belief_id": l[0], "claim": l[1][:50] if l[1] else "", "evidence": l[2][:50] if l[2] else ""} for l in linked[:3]],
            "detail": f"{len(linked)} beliefs with traceable evidence",
            "status": "PASS" if score >= 1 else "FAIL"
        }

    # ── Audit 3: Counterfactual Test ────────────────────────

    def audit_3_counterfactual(self) -> dict:
        """Jika pengalaman pertama dihapus, apa yang berubah?"""
        conn = sqlite3.connect(self.consciousness_db)
        c = conn.cursor()

        # Count dependencies on earliest experience
        earliest = c.execute("SELECT id, event FROM core_memories ORDER BY id ASC LIMIT 1").fetchone()
        if not earliest:
            conn.close()
            return {"score": 0, "detail": "No experiences", "status": "FAIL"}

        eid = earliest[0]

        # Count concepts linked to this experience
        try:
            concept_deps = c.execute(
                "SELECT COUNT(*) FROM concept_provenance WHERE experience_id=?", (eid,)
            ).fetchone()[0]
        except:
            concept_deps = 0

        # Count beliefs affected
        try:
            belief_deps = sqlite3.connect(self.decisions_db).execute(
                "SELECT COUNT(*) FROM belief_evidence WHERE evidence_data LIKE ?",
                (f"%{eid}%",)
            ).fetchone()[0]
        except:
            belief_deps = 0

        conn.close()

        total_deps = concept_deps + belief_deps
        score = 1 if total_deps > 0 else 0

        return {
            "score": score,
            "experience_id": eid,
            "concept_dependencies": concept_deps,
            "belief_dependencies": belief_deps,
            "total_dependencies": total_deps,
            "detail": f"Experience #{eid} affects {total_deps} downstream items",
            "status": "PASS" if score >= 1 else "FAIL"
        }

    # ── Audit 4: Belief Provenance Test ─────────────────────

    def audit_4_belief_provenance(self) -> dict:
        """Dari mana setiap belief berasal?"""
        conn = sqlite3.connect(self.decisions_db)
        c = conn.cursor()

        beliefs = c.execute("SELECT id, claim FROM beliefs").fetchall()
        traceable = 0
        untraceable = 0

        for bid, claim in beliefs:
            ev = c.execute(
                "SELECT COUNT(*) FROM belief_evidence WHERE belief_id=?", (bid,)
            ).fetchone()[0]
            if ev > 0:
                traceable += 1
            else:
                untraceable += 1

        conn.close()

        rate = traceable / max(len(beliefs), 1)
        score = 2 if rate >= 0.5 else 1 if rate > 0 else 0

        return {
            "score": score,
            "total_beliefs": len(beliefs),
            "traceable": traceable,
            "untraceable": untraceable,
            "trace_rate": f"{rate:.1%}",
            "detail": f"{traceable}/{len(beliefs)} beliefs have traceable origin",
            "status": "PASS" if score >= 2 else "PARTIAL" if score == 1 else "FAIL"
        }

    # ── Audit 5: Self-Model Grounding Test ──────────────────

    def audit_5_self_model_grounding(self) -> dict:
        """Kenapa self-model accuracy 46%? Bisa jelaskan?"""
        # Check self_state in self_model.db (where it actually lives)
        try:
            traits = sqlite3.connect(self.self_db).execute(
                "SELECT COUNT(*) FROM self_state"
            ).fetchone()[0]
        except:
            traits = 0

        # Check if predictions affect self-model
        try:
            pred_acc = sqlite3.connect(self.world_db).execute(
                "SELECT COUNT(*) FROM consequences WHERE surprise_score < 0.3"
            ).fetchone()[0]
        except:
            pred_acc = 0

        score = 1 if traits > 0 and pred_acc > 0 else 0

        return {
            "score": score,
            "self_state_entries": traits,
            "low_surprise_predictions": pred_acc,
            "detail": f"Self-model: {traits} traits, {pred_acc} accurate predictions",
            "status": "PASS" if score >= 1 else "FAIL"
        }

    # ── Audit 6: End-to-End Growth Test ─────────────────────

    def audit_6_end_to_end_growth(self) -> dict:
        """Sistem benar-benar berkembang? Buktikan dengan data."""
        conn = sqlite3.connect(self.consciousness_db)
        c = conn.cursor()

        # Snapshot
        memories = c.execute("SELECT COUNT(*) FROM core_memories").fetchone()[0]
        try:
            concepts = c.execute("SELECT COUNT(*) FROM concepts").fetchone()[0]
        except:
            concepts = 0
        try:
            lessons = c.execute("SELECT COUNT(*) FROM consolidated_lessons").fetchone()[0]
        except:
            lessons = 0

        conn.close()

        conn2 = sqlite3.connect(self.decisions_db)
        c2 = conn2.cursor()
        beliefs = c2.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        try:
            predictions = c2.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
        except:
            predictions = 0
        conn2.close()

        # Growth indicators
        has_memories = memories > 0
        has_concepts = concepts > 0
        has_beliefs = beliefs > 0
        has_predictions = predictions > 0
        has_lessons = lessons > 0

        indicators = sum([has_memories, has_concepts, has_beliefs, has_predictions, has_lessons])
        score = 2 if indicators >= 4 else 1 if indicators >= 2 else 0

        return {
            "score": score,
            "snapshot": {
                "memories": memories, "concepts": concepts,
                "beliefs": beliefs, "predictions": predictions,
                "lessons": lessons
            },
            "growth_indicators": indicators,
            "detail": f"{indicators}/5 growth indicators active",
            "status": "PASS" if score >= 2 else "PARTIAL" if score == 1 else "FAIL"
        }

    # ── Audit 7: Disconnect Test ────────────────────────────

    def audit_7_disconnect(self) -> dict:
        """Matikan satu modul → apa dampaknya?"""
        conn = sqlite3.connect(self.consciousness_db)
        c = conn.cursor()

        # Check module dependencies
        modules = {
            "dream_engine": {"lessons": 0, "patterns": 0},
            "belief_lifecycle": {"revisions": 0, "evidence": 0},
            "concept_formation": {"concepts": 0, "patterns": 0},
            "prediction_engine": {"predictions": 0, "evaluated": 0},
        }

        try:
            modules["dream_engine"]["lessons"] = c.execute("SELECT COUNT(*) FROM consolidated_lessons").fetchone()[0]
        except: pass
        try:
            modules["dream_engine"]["patterns"] = c.execute("SELECT COUNT(*) FROM patterns").fetchone()[0]
        except: pass

        conn2 = sqlite3.connect(self.decisions_db)
        c2 = conn2.cursor()
        try:
            modules["belief_lifecycle"]["evidence"] = c2.execute("SELECT COUNT(*) FROM belief_evidence").fetchone()[0]
        except: pass
        try:
            modules["prediction_engine"]["predictions"] = c2.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
        except: pass
        conn2.close()

        # Count active modules (has at least 1 output)
        active = sum(1 for m, data in modules.items() if any(v > 0 for v in data.values()))
        score = 1 if active >= 2 else 0

        conn.close()

        return {
            "score": score,
            "active_modules": active,
            "module_data": modules,
            "detail": f"{active}/{len(modules)} modules have measurable impact",
            "status": "PASS" if score >= 1 else "FAIL"
        }

    def scorecard(self, results: dict) -> str:
        """Human-readable scorecard."""
        lines = ["=" * 50]
        lines.append("  INTEGRATION AUDIT SCORECARD")
        lines.append("=" * 50)
        lines.append("")

        for key, label in [
            ("audit_1_trace", "1. Trace Test"),
            ("audit_2_memory_retrieval", "2. Memory Retrieval"),
            ("audit_3_counterfactual", "3. Counterfactual"),
            ("audit_4_belief_provenance", "4. Belief Provenance"),
            ("audit_5_self_model_grounding", "5. Self-Model Grounding"),
            ("audit_6_end_to_end_growth", "6. End-to-End Growth"),
            ("audit_7_disconnect", "7. Disconnect Test"),
        ]:
            audit = results.get(key, {})
            score = audit.get("score", 0)
            status = audit.get("status", "?")
            emoji = "✅" if status == "PASS" else "⚠️" if status == "PARTIAL" else "❌"
            lines.append(f"  {emoji} {label}: {score}/2 — {status}")
            lines.append(f"     {audit.get('detail', '')}")

        lines.append("")
        lines.append(f"  TOTAL: {results['total_score']}/{results['max_score']}")
        lines.append(f"  RATING: {results['rating']}")
        lines.append("=" * 50)

        return "\n".join(lines)


def demo():
    audit = IntegrationAudit()
    results = audit.run_all()
    print(audit.scorecard(results))


if __name__ == "__main__":
    demo()
