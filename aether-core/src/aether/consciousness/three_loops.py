"""
Three Loops System

Berdasarkan module6.txt:
"Aether harus memiliki 3 siklus berbeda: Fast Loop, Slow Loop, Development Loop"

Fast Loop (detik-menit) — per interaksi:
  Observe → Predict → Act → Measure Error → Learn

Slow Loop (idle) — saat tidak ada user:
  Review → Compress → Organize → Re-evaluate

Development Loop (sleep) — pertumbuhan diri:
  Pre-sleep self-model → Sleep → Post-sleep self-model → Diff

Key principle: "Kalau tidak ada perubahan perilaku dan performa,
maka semua introspeksi hanya menjadi jurnal."
"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime

from aether.paths import get_paths
DB_DIR = get_paths().db


class ThreeLoops:
    """Three-loop system: Fast, Slow, Development."""

    def __init__(self, db_path=None):
        self.db_path = str(db_path or DB_DIR / "consciousness.db")
        self._init_tables()

    def _init_tables(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS loop_cycles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            loop_type TEXT,
            input_data TEXT,
            output_data TEXT,
            changes TEXT,
            duration_ms INTEGER,
            timestamp TEXT
        )''')
        conn.commit()
        conn.close()

    def fast_loop(self, observation: dict, prediction: dict,
                  actual_result: dict) -> dict:
        """Fast Loop: per-interaction learning.

        Observe → Predict → Act → Measure Error → Learn
        """
        import time
        start = time.time()

        # Step 1: Measure error
        predicted = prediction.get("prediction", "unknown")
        actual = actual_result.get("outcome", "unknown")
        confidence = prediction.get("confidence", 0.5)

        was_correct = (predicted == actual)
        error = 0.0 if was_correct else (1.0 - confidence)

        # Step 2: Learn
        lesson = ""
        if was_correct:
            lesson = f"Prediction '{predicted}' confirmed"
        else:
            lesson = f"Predicted '{predicted}' but got '{actual}' — update model"

        # Step 3: Determine what to update
        updates = []
        if error > 0.5:
            updates.append("world_model")
            updates.append("belief")
        elif error > 0.3:
            updates.append("belief")
        elif was_correct:
            updates.append("confidence_boost")

        duration = int((time.time() - start) * 1000)

        result = {
            "loop": "fast",
            "observation": observation,
            "predicted": predicted,
            "actual": actual,
            "was_correct": was_correct,
            "error": round(error, 3),
            "lesson": lesson,
            "updates_needed": updates,
            "duration_ms": duration
        }

        self._log_cycle("fast", observation, result, updates, duration)
        return result

    def slow_loop(self) -> dict:
        """Slow Loop: idle-time knowledge maintenance.

        Review → Compress → Organize → Re-evaluate
        """
        import time
        start = time.time()

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        # Step 1: Review beliefs
        from belief_lifecycle import BeliefLifecycle
        lifecycle = BeliefLifecycle()
        belief_status = lifecycle.status()

        # Step 2: Compress memories (find duplicates)
        c.execute("SELECT id, event, significance FROM core_memories ORDER BY id DESC LIMIT 100")
        memories = c.fetchall()

        duplicate_candidates = []
        seen_events = {}
        for mid, event, sig in memories:
            key = event[:50].lower()
            if key in seen_events:
                duplicate_candidates.append({"id": mid, "duplicate_of": seen_events[key], "event": event[:80]})
            else:
                seen_events[key] = mid

        # Step 3: Re-evaluate belief confidence
        from doubt_engine import DoubtEngine
        doubt = DoubtEngine()
        doubted = doubt.get_most_doubted(5)

        # Step 4: Concept formation check
        from concept_formation import ConceptFormation
        cf = ConceptFormation()
        new_patterns = cf.detect_pattern_candidates()

        duration = int((time.time() - start) * 1000)

        result = {
            "loop": "slow",
            "beliefs_reviewed": belief_status.get("total_beliefs", 0),
            "duplicate_candidates": len(duplicate_candidates),
            "doubted_beliefs": len(doubted),
            "new_patterns_detected": len(new_patterns),
            "actions_taken": []
        }

        if duplicate_candidates:
            result["actions_taken"].append(f"Found {len(duplicate_candidates)} duplicate candidates for merge")
        if doubted:
            result["actions_taken"].append(f"Flagged {len(doubted)} beliefs for re-evaluation")
        if new_patterns:
            result["actions_taken"].append(f"Detected {len(new_patterns)} new patterns")

        conn.close()
        duration = int((time.time() - start) * 1000)
        self._log_cycle("slow", {"trigger": "idle"}, result, result["actions_taken"], duration)
        return result

    def development_loop(self) -> dict:
        """Development Loop: self-growth measurement.

        Pre-sleep self-model → Sleep → Post-sleep self-model → Diff
        """
        import time
        start = time.time()

        # Step 1: Capture pre-sleep self-model
        from self_model import SelfModel
        sm = SelfModel()
        pre_sleep = sm.get_self_report()

        # Step 2: Run sleep cycle
        from dream_engine import DreamEngine
        dream = DreamEngine()
        dream_result = dream.dream()

        # Step 3: Run slow loop tasks
        slow_result = self.slow_loop()

        # Step 4: Capture post-sleep self-model
        sm_post = SelfModel()
        post_sleep = sm_post.get_self_report()

        # Step 5: Compute diff
        pre_conf = pre_sleep.get("overall_confidence", 0)
        post_conf = post_sleep.get("overall_confidence", 0)
        pre_strengths = len(pre_sleep.get("strengths", []))
        post_strengths = len(post_sleep.get("strengths", []))

        diff = {
            "confidence_change": round(post_conf - pre_conf, 4),
            "strengths_change": post_strengths - pre_strengths,
            "traits_changed": {}
        }

        # Compare strengths scores
        pre_scores = {s["key"]: s["score"] for s in pre_sleep.get("strengths", [])}
        post_scores = {s["key"]: s["score"] for s in post_sleep.get("strengths", [])}
        for trait in set(list(pre_scores.keys()) + list(post_scores.keys())):
            old_val = pre_scores.get(trait, 0)
            new_val = post_scores.get(trait, 0)
            if abs(new_val - old_val) > 0.001:
                diff["traits_changed"][trait] = round(new_val - old_val, 4)

        duration = int((time.time() - start) * 1000)

        # Capability check
        capability_changed = bool(diff["traits_changed"]) or diff["confidence_change"] != 0

        result = {
            "loop": "development",
            "pre_sleep": {
                "confidence": pre_conf,
                "strengths_count": pre_strengths
            },
            "post_sleep": {
                "confidence": post_conf,
                "strengths_count": post_strengths
            },
            "diff": diff,
            "capability_changed": capability_changed,
            "dream_summary": dream_result.get("summary", ""),
            "slow_loop_summary": {
                "beliefs_reviewed": slow_result.get("beliefs_reviewed", 0),
                "duplicates_found": slow_result.get("duplicate_candidates", 0)
            }
        }

        self._log_cycle("development", {"trigger": "sleep"}, result,
                       [f"confidence_change={diff['confidence_change']}",
                        f"traits_changed={len(diff['traits_changed'])}"], duration)
        return result

    def _log_cycle(self, loop_type, input_data, output_data, changes, duration):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""INSERT INTO loop_cycles (loop_type, input_data, output_data, changes, duration_ms, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                 (loop_type, json.dumps(input_data), json.dumps(output_data),
                  json.dumps(changes), duration, datetime.now().isoformat()))
        conn.commit()
        conn.close()

    def status(self) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT loop_type, COUNT(*), AVG(duration_ms) FROM loop_cycles GROUP BY loop_type")
        stats = {r[0]: {"count": r[1], "avg_ms": round(r[2], 1)} for r in c.fetchall()}
        c.execute("SELECT COUNT(*) FROM loop_cycles")
        total = c.fetchone()[0]
        conn.close()
        return {"total_cycles": total, "by_loop": stats}


def demo():
    print("=" * 60)
    print("THREE LOOPS SYSTEM — DEMO")
    print("=" * 60)

    loops = ThreeLoops()

    # Fast Loop
    print("\n[1] FAST LOOP — Per-interaction learning")
    result = loops.fast_loop(
        observation={"price": 3420, "trend": "bullish"},
        prediction={"prediction": "price_will_rise", "confidence": 0.7},
        actual_result={"outcome": "price_will_fall"}
    )
    print(f"  Was correct: {result['was_correct']}")
    print(f"  Error: {result['error']}")
    print(f"  Lesson: {result['lesson']}")
    print(f"  Updates needed: {result['updates_needed']}")

    # Slow Loop
    print("\n[2] SLOW LOOP — Idle maintenance")
    result = loops.slow_loop()
    print(f"  Beliefs reviewed: {result['beliefs_reviewed']}")
    print(f"  Duplicate candidates: {result['duplicate_candidates']}")
    print(f"  New patterns: {result['new_patterns_detected']}")
    print(f"  Actions: {result['actions_taken']}")

    # Development Loop
    print("\n[3] DEVELOPMENT LOOP — Self-growth")
    result = loops.development_loop()
    print(f"  Confidence diff: {result['diff']['confidence_change']}")
    print(f"  Traits changed: {result['diff']['traits_changed']}")
    print(f"  Capability changed: {result['capability_changed']}")
    print(f"  Dream: {result['dream_summary'][:80]}...")

    # Status
    print(f"\n[4] Status: {json.dumps(loops.status(), indent=2)}")


if __name__ == "__main__":
    demo()
