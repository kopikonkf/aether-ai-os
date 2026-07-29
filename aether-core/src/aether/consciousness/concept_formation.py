"""
Concept Formation Engine v2 — Proper Pipeline

Berdasarkan module13 + Dee's guidance:
Bottleneck bukan Vision → Concept.
Tapi Experience → Generalization.

Pipeline yang benar:
  Observation → Pattern Candidates → Confidence Scoring → Concept
  → Belief Update → Prediction → Outcome Verification

Konsep yang tidak pernah diuji = asumsi.
Konsep yang diuji dan terbukti = pengetahuan.
"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime
from collections import Counter

from aether.paths import get_paths
DB_DIR = get_paths().db


class ConceptFormation:
    """Concept Formation with proper pipeline and outcome verification."""

    def __init__(self, db_path=None):
        self.db_path = str(db_path or DB_DIR / "consciousness.db")
        self._init_tables()

    def _init_tables(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        # Raw observations
        c.execute('''CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT DEFAULT 'experience',
            content TEXT NOT NULL,
            properties TEXT DEFAULT '{}',
            timestamp TEXT
        )''')

        # Pattern candidates (not yet concepts)
        c.execute('''CREATE TABLE IF NOT EXISTS pattern_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            observation_ids TEXT DEFAULT '[]',
            frequency INTEGER DEFAULT 1,
            confidence REAL DEFAULT 0.0,
            status TEXT DEFAULT 'candidate',
            first_seen TEXT,
            last_seen TEXT,
            evidence_for INTEGER DEFAULT 0,
            evidence_against INTEGER DEFAULT 0
        )''')

        # Validated concepts
        c.execute('''CREATE TABLE IF NOT EXISTS concepts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            level TEXT DEFAULT 'concept',
            pattern_ids TEXT DEFAULT '[]',
            parent_concept_id INTEGER,
            confidence REAL DEFAULT 0.0,
            predictions_made INTEGER DEFAULT 0,
            predictions_correct INTEGER DEFAULT 0,
            accuracy REAL DEFAULT 0.0,
            status TEXT DEFAULT 'unvalidated',
            created TEXT,
            last_updated TEXT,
            FOREIGN KEY (parent_concept_id) REFERENCES concepts(id)
        )''')

        # Outcome verification log
        c.execute('''CREATE TABLE IF NOT EXISTS outcome_verifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            concept_id INTEGER,
            prediction TEXT,
            expected_outcome TEXT,
            actual_outcome TEXT,
            was_correct BOOLEAN,
            confidence_before REAL,
            confidence_after REAL,
            timestamp TEXT,
            FOREIGN KEY (concept_id) REFERENCES concepts(id)
        )''')

        conn.commit()
        conn.close()

    # ==================== STEP 1: OBSERVATION ====================

    def add_observation(self, content: str, source: str = "experience",
                        properties: dict = None) -> dict:
        """Add a raw observation. This is the seed of all knowledge."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        now = datetime.now().isoformat()

        c.execute("""INSERT INTO observations (source, content, properties, timestamp)
                    VALUES (?, ?, ?, ?)""",
                 (source, content, json.dumps(properties or {}), now))
        obs_id = c.lastrowid

        conn.commit()
        conn.close()

        return {"observation_id": obs_id, "content": content[:100]}

    # ==================== STEP 2: PATTERN CANDIDATES ====================

    def detect_pattern_candidates(self, min_frequency: int = 2) -> list:
        """Find repeated patterns from observations. Not concepts yet — candidates."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        now = datetime.now().isoformat()

        c.execute("SELECT id, content, properties FROM observations ORDER BY timestamp DESC LIMIT 500")
        observations = c.fetchall()

        if len(observations) < min_frequency:
            conn.close()
            return []

        # Group by content similarity (simple: exact match on key phrases)
        phrase_groups = {}
        for obs_id, content, props in observations:
            # Extract key phrases (words > 4 chars)
            words = [w.lower() for w in content.split() if len(w) > 4]
            for word in words:
                if word not in phrase_groups:
                    phrase_groups[word] = []
                phrase_groups[word].append(obs_id)

        new_candidates = []
        for phrase, obs_ids in phrase_groups.items():
            if len(obs_ids) >= min_frequency:
                # Check if candidate exists
                c.execute("SELECT id, frequency FROM pattern_candidates WHERE name = ?", (phrase,))
                existing = c.fetchone()

                if existing:
                    c.execute("UPDATE pattern_candidates SET frequency = ?, last_seen = ?, observation_ids = ? WHERE id = ?",
                             (len(obs_ids), now, json.dumps(obs_ids), existing[0]))
                else:
                    c.execute("""INSERT INTO pattern_candidates 
                                (name, description, observation_ids, frequency, confidence, status, first_seen, last_seen)
                                VALUES (?, ?, ?, ?, 0.0, 'candidate', ?, ?)""",
                             (phrase, f"Pattern from {len(obs_ids)} observations",
                              json.dumps(obs_ids), len(obs_ids), now, now))
                    new_candidates.append({"name": phrase, "frequency": len(obs_ids)})

        conn.commit()
        conn.close()

        return new_candidates

    # ==================== STEP 3: CONFIDENCE SCORING ====================

    def score_candidate(self, candidate_id: int) -> dict:
        """Score a pattern candidate. Not yet a concept."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute("SELECT name, frequency, evidence_for, evidence_against FROM pattern_candidates WHERE id = ?",
                 (candidate_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            return {"error": "Candidate not found"}

        name, freq, ev_for, ev_against = row

        # Confidence = f(frequency, evidence_ratio)
        total_evidence = ev_for + ev_against
        if total_evidence == 0:
            confidence = min(0.3, freq * 0.05)  # Low without evidence
        else:
            evidence_ratio = ev_for / total_evidence
            confidence = evidence_ratio * min(1.0, freq * 0.1)

        c.execute("UPDATE pattern_candidates SET confidence = ? WHERE id = ?", (confidence, candidate_id))
        conn.commit()
        conn.close()

        return {"candidate_id": candidate_id, "name": name, "confidence": confidence, "frequency": freq}

    def add_evidence_to_candidate(self, candidate_id: int, supports: bool,
                                   evidence: str = "") -> dict:
        """Add evidence for or against a pattern candidate."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        if supports:
            c.execute("UPDATE pattern_candidates SET evidence_for = evidence_for + 1 WHERE id = ?",
                     (candidate_id,))
        else:
            c.execute("UPDATE pattern_candidates SET evidence_against = evidence_against + 1 WHERE id = ?",
                     (candidate_id,))

        conn.commit()
        conn.close()

        return self.score_candidate(candidate_id)

    # ==================== STEP 4: CONCEPT FORMATION ====================

    def promote_to_concept(self, candidate_id: int, concept_name: str = None,
                           description: str = "") -> dict:
        """Promote a validated pattern candidate to a concept."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        now = datetime.now().isoformat()

        c.execute("SELECT name, frequency, confidence, observation_ids FROM pattern_candidates WHERE id = ?",
                 (candidate_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            return {"error": "Candidate not found"}

        name, freq, confidence, obs_ids = row

        if confidence < 0.2:
            conn.close()
            return {"error": f"Confidence too low ({confidence:.2f}). Need more evidence."}

        concept_name = concept_name or name.upper()

        # Check if concept exists
        c.execute("SELECT id FROM concepts WHERE name = ?", (concept_name,))
        if c.fetchone():
            conn.close()
            return {"error": "Concept already exists"}

        c.execute("""INSERT INTO concepts 
                    (name, description, level, pattern_ids, confidence, status, created, last_updated)
                    VALUES (?, ?, 'concept', ?, ?, 'unvalidated', ?, ?)""",
                 (concept_name, description or f"Formed from pattern '{name}' with {freq} observations",
                  json.dumps([candidate_id]), confidence, now, now))
        concept_id = c.lastrowid

        # Update candidate status
        c.execute("UPDATE pattern_candidates SET status = 'promoted' WHERE id = ?", (candidate_id,))

        conn.commit()
        conn.close()

        return {"concept_id": concept_id, "name": concept_name, "confidence": confidence}

    # ==================== STEP 5: PREDICTION ====================

    def predict(self, concept_id: int, context: str = "") -> dict:
        """Make a prediction based on a concept."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute("SELECT name, confidence, accuracy, predictions_made, predictions_correct FROM concepts WHERE id = ?",
                 (concept_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            return {"error": "Concept not found"}

        name, confidence, accuracy, made, correct = row

        prediction = {
            "concept": name,
            "predicted_outcome": f"Based on concept '{name}', expected pattern will continue",
            "confidence": confidence,
            "historical_accuracy": accuracy,
            "predictions_made": made,
            "predictions_correct": correct,
            "context": context
        }

        # Increment predictions_made
        c.execute("UPDATE concepts SET predictions_made = predictions_made + 1 WHERE id = ?",
                 (concept_id,))
        conn.commit()
        conn.close()

        return prediction

    # ==================== STEP 6: OUTCOME VERIFICATION ====================

    def verify_outcome(self, concept_id: int, prediction: str,
                       expected: str, actual: str) -> dict:
        """Verify if a prediction was correct. This is where concepts become knowledge."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        now = datetime.now().isoformat()

        c.execute("SELECT confidence, predictions_correct, predictions_made FROM concepts WHERE id = ?",
                 (concept_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            return {"error": "Concept not found"}

        conf_before = row[0]
        correct_before = row[1]
        made = row[2]

        # Determine if prediction was correct
        was_correct = self._evaluate_outcome(expected, actual)

        # Update confidence based on outcome
        if was_correct:
            new_confidence = min(0.95, conf_before + 0.05)
            new_correct = correct_before + 1
        else:
            new_confidence = max(0.05, conf_before - 0.08)  # Penalize more for failure
            new_correct = correct_before

        new_accuracy = new_correct / max(1, made)

        # Update concept
        c.execute("""UPDATE concepts SET confidence = ?, predictions_correct = ?, 
                    accuracy = ?, last_updated = ? WHERE id = ?""",
                 (new_confidence, new_correct, new_accuracy, now, concept_id))

        # Log verification
        c.execute("""INSERT INTO outcome_verifications 
                    (concept_id, prediction, expected_outcome, actual_outcome, was_correct,
                     confidence_before, confidence_after, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                 (concept_id, prediction, expected, actual, was_correct,
                  conf_before, new_confidence, now))

        # Update status based on accuracy
        if made >= 10:
            if new_accuracy > 0.7:
                c.execute("UPDATE concepts SET status = 'validated' WHERE id = ?", (concept_id,))
            elif new_accuracy < 0.3:
                c.execute("UPDATE concepts SET status = 'invalidated' WHERE id = ?", (concept_id,))

        conn.commit()
        conn.close()

        return {
            "concept_id": concept_id,
            "was_correct": was_correct,
            "confidence_before": conf_before,
            "confidence_after": new_confidence,
            "accuracy": new_accuracy,
            "status": "validated" if new_accuracy > 0.7 and made >= 10 else
                     "invalidated" if new_accuracy < 0.3 and made >= 10 else "unvalidated"
        }

    def _evaluate_outcome(self, expected: str, actual: str) -> bool:
        """Simple outcome evaluation."""
        expected_lower = expected.lower().strip()
        actual_lower = actual.lower().strip()

        # Direct match
        if expected_lower == actual_lower:
            return True

        # Partial match
        if expected_lower in actual_lower or actual_lower in expected_lower:
            return True

        # Keyword match
        exp_words = set(expected_lower.split())
        act_words = set(actual_lower.split())
        overlap = len(exp_words & act_words)
        if overlap >= len(exp_words) * 0.5:
            return True

        return False

    # ==================== STEP 7: BELIEF UPDATE ====================

    def update_belief_from_concept(self, concept_id: int) -> dict:
        """Update beliefs based on validated concept."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute("SELECT name, confidence, accuracy, status FROM concepts WHERE id = ?",
                 (concept_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            return {"error": "Concept not found"}

        name, confidence, accuracy, status = row

        if status != "validated":
            conn.close()
            return {"message": f"Concept not validated yet (status={status})"}

        # Check if belief exists
        c.execute("SELECT id, confidence FROM beliefs WHERE claim = ?", (name,))
        belief = c.fetchone()

        if belief:
            # Update belief confidence
            old_conf = belief[1]
            new_conf = min(0.95, old_conf + accuracy * 0.1)
            c.execute("UPDATE beliefs SET confidence = ?, updated = ? WHERE id = ?",
                     (new_conf, datetime.now().isoformat(), belief[0]))
            return {"belief_id": belief[0], "action": "updated", "old": old_conf, "new": new_conf}
        else:
            # Create new belief from concept
            c.execute("""INSERT INTO beliefs (claim, confidence, support_strength, attack_strength, evidence_count, created, updated)
                        VALUES (?, ?, ?, 0.0, 1, ?, ?)""",
                     (name, confidence, accuracy, datetime.now().isoformat(), datetime.now().isoformat()))
            return {"belief_id": c.lastrowid, "action": "created", "confidence": confidence}

    # ==================== QUERY ====================

    def get_pipeline_status(self) -> dict:
        """Full pipeline status."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute("SELECT COUNT(*) FROM observations")
        obs_count = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM pattern_candidates WHERE status = 'candidate'")
        candidates = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM pattern_candidates WHERE status = 'promoted'")
        promoted = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM concepts")
        concepts = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM concepts WHERE status = 'validated'")
        validated = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM concepts WHERE status = 'invalidated'")
        invalidated = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM outcome_verifications")
        verifications = c.fetchone()[0]

        c.execute("SELECT AVG(confidence) FROM concepts")
        avg_conf = c.fetchone()[0] or 0

        c.execute("SELECT AVG(accuracy) FROM concepts WHERE predictions_made > 0")
        avg_acc = c.fetchone()[0] or 0

        conn.close()

        return {
            "pipeline": {
                "observations": obs_count,
                "pattern_candidates": candidates,
                "promoted_patterns": promoted,
                "concepts": concepts,
                "validated_concepts": validated,
                "invalidated_concepts": invalidated,
                "verifications": verifications
            },
            "quality": {
                "avg_concept_confidence": round(avg_conf, 3),
                "avg_concept_accuracy": round(avg_acc, 3),
                "validation_rate": round(validated / max(1, concepts), 3)
            },
            "flow": f"{obs_count} obs → {candidates} candidates → {promoted} promoted → {concepts} concepts ({validated} validated)"
        }

    def get_concept_with_history(self, concept_id: int) -> dict:
        """Get full concept lifecycle."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute("SELECT * FROM concepts WHERE id = ?", (concept_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            return {"error": "Concept not found"}

        c.execute("""SELECT prediction, expected_outcome, actual_outcome, was_correct,
                     confidence_before, confidence_after, timestamp 
                     FROM outcome_verifications WHERE concept_id = ? ORDER BY timestamp""",
                 (concept_id,))
        verifications = [{
            "prediction": r[0], "expected": r[1], "actual": r[2],
            "correct": bool(r[3]), "conf_before": r[4], "conf_after": r[5],
            "timestamp": r[6]
        } for r in c.fetchall()]

        conn.close()

        return {
            "name": row[1], "description": row[2], "confidence": row[6],
            "accuracy": row[9], "status": row[10],
            "predictions_made": row[7], "predictions_correct": row[8],
            "verifications": verifications
        }

    def status(self) -> dict:
        """Get formation status."""
        pipeline = self.get_pipeline_status()
        return {
            **pipeline,
            "health": "active" if pipeline["pipeline"]["concepts"] > 0 else "seedling"
        }


def demo():
    """Full pipeline demo."""
    cf = ConceptFormation()

    print("=" * 60)
    print("CONCEPT FORMATION v2 — PROPER PIPELINE")
    print("=" * 60)

    # Step 1: Observations
    print("\n[1] OBSERVATIONS")
    observations = [
        "Chart shows uptrend with strong momentum",
        "Chart shows uptrend after breakout",
        "Chart shows uptrend with volume confirmation",
        "Chart shows downtrend after rejection",
        "Chart shows consolidation after uptrend",
        "Chart shows reversal at resistance",
    ]
    for obs in observations:
        cf.add_observation(obs, source="vision")
    print(f"  Added {len(observations)} observations")

    # Step 2: Pattern candidates
    print("\n[2] PATTERN CANDIDATES")
    candidates = cf.detect_pattern_candidates(min_frequency=2)
    for c in candidates:
        print(f"  Candidate: {c['name']} (freq: {c['frequency']})")

    # Step 3: Score candidates
    print("\n[3] CONFIDENCE SCORING")
    conn = sqlite3.connect(cf.db_path)
    c = conn.cursor()
    c.execute("SELECT id, name, confidence FROM pattern_candidates")
    for row in c.fetchall():
        result = cf.score_candidate(row[0])
        print(f"  {row[1]}: confidence={result['confidence']:.3f}")
    conn.close()

    # Step 4: Add evidence and promote
    print("\n[4] ADD EVIDENCE → PROMOTE")
    conn = sqlite3.connect(cf.db_path)
    c = conn.cursor()
    c.execute("SELECT id FROM pattern_candidates WHERE name = 'uptrend'")
    row = c.fetchone()
    if row:
        cf.add_evidence_to_candidate(row[0], True, "observed in charts")
        cf.add_evidence_to_candidate(row[0], True, "confirmed by volume")
        cf.add_evidence_to_candidate(row[0], True, "matches historical pattern")
        result = cf.promote_to_concept(row[0], "UPTREND", "Price moving upward with momentum")
        print(f"  Promoted: {result}")
    conn.close()

    # Step 5: Predict
    print("\n[5] PREDICTION")
    conn = sqlite3.connect(cf.db_path)
    c = conn.cursor()
    c.execute("SELECT id, name FROM concepts")
    for row in c.fetchall():
        pred = cf.predict(row[0], "New chart showing upward movement")
        print(f"  {row[1]}: confidence={pred['confidence']:.3f}, accuracy={pred['historical_accuracy']:.3f}")

        # Step 6: Verify outcomes
        print("\n[6] OUTCOME VERIFICATION")
        verify = cf.verify_outcome(row[0], "uptrend continues", "uptrend continues", "uptrend continues")
        print(f"  Result: correct={verify['was_correct']}, conf: {verify['confidence_before']:.3f} → {verify['confidence_after']:.3f}")

        verify2 = cf.verify_outcome(row[0], "uptrend continues", "uptrend continues", "downtrend started")
        print(f"  Result: correct={verify2['was_correct']}, conf: {verify2['confidence_before']:.3f} → {verify2['confidence_after']:.3f}")
    conn.close()

    # Pipeline status
    print("\n[7] PIPELINE STATUS")
    print(json.dumps(cf.get_pipeline_status(), indent=2))


if __name__ == "__main__":
    demo()
