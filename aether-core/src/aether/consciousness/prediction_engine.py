"""
Prediction Engine — Deliverable 3, Sprint #3

Belief harus dipaksa membuat prediksi.

Flow:
  belief → prediction → outcome → evidence → confidence update

Bukan passive storage.
Belief yang tidak pernah diprediksi = dormant.
"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime

from aether.paths import get_paths
DB_DIR = get_paths().db


class PredictionEngine:
    """Force beliefs to make predictions, then evaluate outcomes."""

    def __init__(self):
        self.decisions_db = str(DB_DIR / "decisions.db")
        self.consciousness_db = str(DB_DIR / "consciousness.db")
        self._init_tables()

    def _init_tables(self):
        conn = sqlite3.connect(self.decisions_db)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            belief_id INTEGER NOT NULL,
            prediction_text TEXT NOT NULL,
            prediction_type TEXT,
            predicted_outcome TEXT,
            confidence REAL DEFAULT 0.5,
            actual_outcome TEXT,
            was_correct INTEGER,
            surprise REAL,
            evidence_id INTEGER,
            status TEXT DEFAULT 'pending',
            created TEXT,
            evaluated TEXT,
            FOREIGN KEY (belief_id) REFERENCES beliefs(id)
        )''')
        conn.commit()
        conn.close()

    def generate_prediction(self, belief_id: int, context: str = "") -> dict:
        """Generate a prediction from a belief.
        
        Belief: "reversals happen at extremes"
        Context: "price at 3350 (extreme zone)"
        Prediction: "reversal expected, probability=0.65"
        """
        conn = sqlite3.connect(self.decisions_db)
        c = conn.cursor()

        belief = c.execute("SELECT id, claim, confidence FROM beliefs WHERE id=?",
                          (belief_id,)).fetchone()
        if not belief:
            conn.close()
            return {"error": f"Belief {belief_id} not found"}

        # Generate prediction based on belief claim
        claim = belief[1].lower()
        conf = belief[2]

        # Simple prediction extraction from claim
        if "reversal" in claim:
            pred_type = "direction"
            predicted = "reversal"
            pred_text = f"Based on '{belief[1]}': reversal expected (conf={conf:.2f})"
        elif "trend" in claim:
            pred_type = "direction"
            predicted = "continuation"
            pred_text = f"Based on '{belief[1]}': trend continues (conf={conf:.2f})"
        elif "support" in claim or "resistance" in claim:
            pred_type = "level"
            predicted = "bounce"
            pred_text = f"Based on '{belief[1]}': price bounces at level (conf={conf:.2f})"
        elif "volume" in claim:
            pred_type = "confirmation"
            predicted = "confirmed_move"
            pred_text = f"Based on '{belief[1]}': move confirmed by volume (conf={conf:.2f})"
        elif "random" in claim:
            pred_type = "direction"
            predicted = "unpredictable"
            pred_text = f"Based on '{belief[1]}': outcome unpredictable (conf={conf:.2f})"
        else:
            pred_type = "general"
            predicted = "unknown"
            pred_text = f"Based on '{belief[1]}': general prediction (conf={conf:.2f})"

        if context:
            pred_text += f" [context: {context}]"

        now = datetime.now().isoformat()
        c.execute('''INSERT INTO predictions
                    (belief_id, prediction_text, prediction_type, predicted_outcome,
                     confidence, status, created)
                    VALUES (?, ?, ?, ?, ?, 'pending', ?)''',
                 (belief_id, pred_text, pred_type, predicted, conf, now))

        pred_id = c.lastrowid
        conn.commit()
        conn.close()

        return {
            "prediction_id": pred_id,
            "belief_id": belief_id,
            "belief_claim": belief[1],
            "prediction": pred_text,
            "type": pred_type,
            "predicted_outcome": predicted,
            "confidence": conf,
            "status": "pending"
        }

    def record_outcome(self, prediction_id: int, actual_outcome: str) -> dict:
        """Record actual outcome and evaluate prediction."""
        conn = sqlite3.connect(self.decisions_db)
        c = conn.cursor()

        pred = c.execute(
            "SELECT id, belief_id, predicted_outcome, confidence FROM predictions WHERE id=?",
            (prediction_id,)).fetchone()
        if not pred:
            conn.close()
            return {"error": f"Prediction {prediction_id} not found"}

        # Evaluate: was prediction correct?
        predicted = pred[2].lower() if pred[2] else ""
        actual = actual_outcome.lower()

        # Simple matching
        was_correct = None
        if "reversal" in predicted and "reversal" in actual:
            was_correct = 1
        elif "continuation" in predicted and ("continuation" in actual or "continued" in actual):
            was_correct = 1
        elif "bounce" in predicted and "bounce" in actual:
            was_correct = 1
        elif "unpredictable" in predicted:
            was_correct = 1  # Can't be wrong if you predict unpredictability
        elif predicted and actual:
            was_correct = 0

        surprise = 0.0
        if was_correct is not None:
            surprise = abs(pred[3] - (1.0 if was_correct else 0.0))

        now = datetime.now().isoformat()
        c.execute('''UPDATE predictions SET actual_outcome=?, was_correct=?,
                    surprise=?, status='evaluated', evaluated=?
                    WHERE id=?''',
                 (actual_outcome, was_correct, surprise, now, prediction_id))

        # Update belief based on outcome
        if was_correct is not None:
            belief = c.execute("SELECT confidence FROM beliefs WHERE id=?",
                             (pred[1],)).fetchone()
            if belief:
                old_conf = belief[0]
                if was_correct:
                    new_conf = min(1.0, old_conf + 0.05)
                else:
                    new_conf = max(0.0, old_conf - 0.10)
                c.execute("UPDATE beliefs SET confidence=?, updated=? WHERE id=?",
                         (new_conf, now, pred[1]))

                # Add evidence
                c.execute('''INSERT INTO belief_evidence
                            (belief_id, evidence_type, source, detail, impact, created)
                            VALUES (?, ?, 'prediction_engine', ?, ?, ?)''',
                         (pred[1], 'supporting' if was_correct else 'opposing',
                          f"Prediction #{prediction_id}: {actual_outcome}",
                          0.05 if was_correct else -0.10, now))

        conn.commit()
        conn.close()

        return {
            "prediction_id": prediction_id,
            "predicted": pred[2],
            "actual": actual_outcome,
            "was_correct": was_correct,
            "surprise": round(surprise, 3),
            "status": "evaluated"
        }

    def get_pending(self) -> list:
        """Get all pending predictions."""
        conn = sqlite3.connect(self.decisions_db)
        c = conn.cursor()
        rows = c.execute(
            "SELECT id, belief_id, prediction_text, confidence, created FROM predictions WHERE status='pending'"
        ).fetchall()
        conn.close()
        return [{"id": r[0], "belief_id": r[1], "prediction": r[2],
                "confidence": r[3], "created": r[4]} for r in rows]

    def get_stats(self) -> dict:
        """Prediction engine statistics."""
        conn = sqlite3.connect(self.decisions_db)
        c = conn.cursor()

        total = c.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
        pending = c.execute("SELECT COUNT(*) FROM predictions WHERE status='pending'").fetchone()[0]
        evaluated = c.execute("SELECT COUNT(*) FROM predictions WHERE status='evaluated'").fetchone()[0]
        correct = c.execute("SELECT COUNT(*) FROM predictions WHERE was_correct=1").fetchone()[0]
        incorrect = c.execute("SELECT COUNT(*) FROM predictions WHERE was_correct=0").fetchone()[0]

        accuracy = correct / max(correct + incorrect, 1)

        # Beliefs that never predicted
        all_beliefs = c.execute("SELECT id, claim FROM beliefs").fetchall()
        predicting_beliefs = set(r[0] for r in c.execute(
            "SELECT DISTINCT belief_id FROM predictions"
        ).fetchall())
        dormant_beliefs = [
            {"id": b[0], "claim": b[1]}
            for b in all_beliefs if b[0] not in predicting_beliefs
        ]

        conn.close()

        return {
            "total_predictions": total,
            "pending": pending,
            "evaluated": evaluated,
            "correct": correct,
            "incorrect": incorrect,
            "accuracy": round(accuracy, 3),
            "dormant_beliefs": dormant_beliefs,
            "dormant_count": len(dormant_beliefs)
        }


def demo():
    engine = PredictionEngine()
    print("=== Prediction Engine ===\n")

    stats = engine.get_stats()
    print(f"Total predictions: {stats['total_predictions']}")
    print(f"Pending: {stats['pending']}")
    print(f"Evaluated: {stats['evaluated']}")
    print(f"Accuracy: {stats['accuracy']:.1%}")
    print(f"Dormant beliefs: {stats['dormant_count']}")

    if stats["dormant_beliefs"]:
        print(f"\n⚠️ Beliefs that never predicted:")
        for b in stats["dormant_beliefs"]:
            print(f"  #{b['id']}: {b['claim']}")

    # Generate predictions for dormant beliefs
    if stats["dormant_beliefs"]:
        print(f"\nGenerating predictions for dormant beliefs...")
        for b in stats["dormant_beliefs"]:
            result = engine.generate_prediction(b["id"])
            if "error" not in result:
                print(f"  ✅ #{b['id']}: {result['prediction'][:60]}...")


if __name__ == "__main__":
    demo()
