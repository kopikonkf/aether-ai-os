"""
Idle Consolidation — Module 5

Saat idle (tidak ada input baru), Aether "tidur":
  Raw Experiences → Consolidation → Concept Formation → Belief Review → Memory Compression

Bukan membuat fitur baru.
Bukan membaca internet.
Bukan coding.
Tapi merapikan pengalaman yang sudah ada.

Mirip manusia:
  Kita tidak mengingat setiap sarapan.
  Kita mengingat pola.
"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime

from aether.paths import get_paths
DB_DIR = get_paths().db


class IdleConsolidator:
    """Run during idle time — consolidate, compress, learn."""

    def __init__(self):
        self.consciousness_db = str(DB_DIR / "consciousness.db")
        self.decisions_db = str(DB_DIR / "decisions.db")

    def run_full_cycle(self) -> dict:
        """Full idle consolidation cycle."""
        report = {
            "timestamp": datetime.now().isoformat(),
            "steps": {}
        }

        # Step 1: Consolidate raw experiences into episodes
        report["steps"]["consolidation"] = self._consolidate_experiences()

        # Step 2: Run generalization pipeline
        report["steps"]["generalization"] = self._run_generalization()

        # Step 3: Review beliefs
        report["steps"]["belief_review"] = self._review_beliefs()

        # Step 4: Compress memory
        report["steps"]["memory_compression"] = self._compress_memory()

        # Step 5: Dream consolidation (lessons)
        report["steps"]["dream"] = self._dream_consolidation()

        return report

    def _consolidate_experiences(self) -> dict:
        """Group raw experiences into episodes."""
        try:
            from consciousness.episode_maker import EpisodeMaker
            maker = EpisodeMaker()

            # Get recent experiences
            conn = sqlite3.connect(self.consciousness_db)
            c = conn.cursor()
            recent = c.execute(
                "SELECT id, event, significance FROM core_memories ORDER BY id DESC LIMIT 10"
            ).fetchall()
            conn.close()

            processed = 0
            for eid, event, sig in recent:
                if sig and sig > 0.7:
                    maker.process_event("high_significance", {"event": event, "significance": sig})
                    processed += 1

            return {"status": "ok", "experiences_processed": processed}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _run_generalization(self) -> dict:
        """Run Experience → Generalization pipeline."""
        try:
            from consciousness.generalization import GeneralizationEngine
            engine = GeneralizationEngine()
            result = engine.run_pipeline()
            return {
                "status": "ok",
                "patterns_found": result["pattern_candidates"],
                "concepts_graduated": result["concepts_graduated"],
                "knowledge_yield": result["knowledge_yield"]
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _review_beliefs(self) -> dict:
        """Review beliefs that are due for review."""
        try:
            from consciousness.belief_audit import BeliefAuditor
            auditor = BeliefAuditor()

            # Check for stale beliefs
            stale = auditor.audit_3_untested_30_days()
            no_ev = auditor.audit_1_no_evidence()

            return {
                "status": "ok",
                "stale_beliefs": len(stale),
                "no_evidence_beliefs": len(no_ev),
                "needs_attention": len(stale) + len(no_ev)
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _compress_memory(self) -> dict:
        """Compress duplicate/low-value memories."""
        try:
            from consciousness.no_dupe_guard import NoDupeGuard
            guard = NoDupeGuard()
            status = guard.status()

            return {
                "status": "ok",
                "total_entries": status["total_entries"],
                "capacity_used": status["capacity_used"],
                "avg_strength": status["avg_strength"]
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _dream_consolidation(self) -> dict:
        """Run dream engine for lesson extraction."""
        try:
            from consciousness.dream_engine import DreamEngine
            engine = DreamEngine()
            result = engine.dream()
            return {
                "status": "ok",
                "lessons": result.get("lessons_created", 0),
                "patterns": result.get("patterns_found", 0)
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def summary(self, report: dict) -> str:
        """Human-readable summary."""
        lines = ["=== Idle Consolidation Report ==="]
        for step, data in report.get("steps", {}).items():
            status = data.get("status", "?")
            emoji = "✅" if status == "ok" else "❌"
            lines.append(f"  {emoji} {step}: {status}")
            for k, v in data.items():
                if k != "status":
                    lines.append(f"     {k}: {v}")
        return "\n".join(lines)


def demo():
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    consolidator = IdleConsolidator()
    print("=== Idle Consolidation — Full Cycle ===\n")
    report = consolidator.run_full_cycle()
    print(consolidator.summary(report))


if __name__ == "__main__":
    demo()
