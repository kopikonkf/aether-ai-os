"""
Generalization Engine — Module 16

Experience → Generalization Pipeline

Bukan langsung:
  3 chart → UPTREND concept

Tapi:
  Observation → Pattern Candidates → Confidence Scoring → Concept Formation → Belief Update → Prediction → Outcome Verification

Karena konsep yang tidak pernah diuji hanya asumsi.

Knowledge Yield:
  100 experiences → berapa concepts?
  10 concepts → berapa beliefs?
  5 beliefs → berapa validated?
"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime
from collections import Counter

from aether.paths import get_paths
DB_DIR = get_paths().db


class GeneralizationEngine:
    """Experience → Generalization pipeline."""

    def __init__(self):
        self.consciousness_db = str(DB_DIR / "consciousness.db")
        self.decisions_db = str(DB_DIR / "decisions.db")
        self.world_db = str(DB_DIR / "world_model.db")

    # ── STEP 1: Extract observations from experiences ──────────

    def extract_observations(self, limit: int = 50) -> list:
        """Pull raw observations from core_memories."""
        conn = sqlite3.connect(self.consciousness_db)
        c = conn.cursor()
        rows = c.execute('''SELECT id, event, significance, emotional_weight, impact_on_identity
                           FROM core_memories ORDER BY id DESC LIMIT ?''', (limit,)).fetchall()
        conn.close()

        observations = []
        for r in rows:
            observations.append({
                "id": r[0], "content": r[1], "significance": r[2],
                "emotion": r[3], "type": r[4]
            })
        return observations

    # ── STEP 2: Find pattern candidates ────────────────────────

    def find_pattern_candidates(self, observations: list) -> list:
        """Group similar observations into pattern candidates.
        
        Uses keyword clustering — not deep NLP, but effective for structured data.
        """
        # Extract keywords from observations
        keyword_groups = Counter()
        keyword_observations = {}

        for obs in observations:
            words = set(obs["content"].lower().split())
            # Filter stopwords
            stopwords = {"the", "a", "an", "is", "was", "were", "been", "be",
                        "have", "has", "had", "do", "does", "did", "will", "would",
                        "could", "should", "may", "might", "shall", "can", "need",
                        "dare", "ought", "used", "to", "of", "in", "for", "on",
                        "with", "at", "by", "from", "as", "into", "through", "during",
                        "before", "after", "above", "below", "between", "out", "off",
                        "over", "under", "again", "further", "then", "once", "that",
                        "this", "these", "those", "and", "but", "or", "nor", "not",
                        "so", "yet", "both", "either", "neither", "each", "every",
                        "all", "any", "few", "more", "most", "other", "some", "such",
                        "no", "only", "own", "same", "than", "too", "very", "just",
                        "because", "if", "when", "where", "how", "what", "which",
                        "who", "whom", "whose", "why", "saya", "dia", "ini", "itu",
                        "dan", "atau", "tapi", "yang", "untuk", "dengan", "dari",
                        "pada", "ke", "di", "akan", "sudah", "belum", "ada", "tidak"}
            keywords = words - stopwords
            keywords = {k for k in keywords if len(k) > 2}

            for kw in keywords:
                keyword_groups[kw] += 1
                if kw not in keyword_observations:
                    keyword_observations[kw] = []
                keyword_observations[kw].append(obs["id"])

        # Find keywords that appear in 2+ observations
        pattern_candidates = []
        for keyword, count in keyword_groups.most_common(20):
            if count >= 2:
                obs_ids = keyword_observations[keyword]
                pattern_candidates.append({
                    "keyword": keyword,
                    "count": count,
                    "observation_ids": obs_ids,
                    "confidence": min(1.0, count / len(observations)),
                    "status": "candidate"
                })

        return pattern_candidates

    # ── STEP 3: Score pattern confidence ───────────────────────

    def score_patterns(self, candidates: list) -> list:
        """Score pattern candidates by confidence.
        
        Confidence = frequency × consistency × recency
        """
        scored = []
        for c in candidates:
            freq_score = min(1.0, c["count"] / 5)  # 5 occurrences = max freq score
            consistency = c["confidence"]  # already 0-1
            # Recency: more recent = higher (we don't have timestamps per keyword, so use count as proxy)
            recency = min(1.0, c["count"] / 3)

            score = (freq_score * 0.4 + consistency * 0.4 + recency * 0.2)
            c["score"] = round(score, 3)
            c["status"] = "scored"
            scored.append(c)

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored

    # ── STEP 4: Graduate to concepts ───────────────────────────

    def graduate_to_concepts(self, scored_patterns: list, min_score: float = 0.3) -> list:
        """Graduate scored patterns to concepts if above threshold.
        
        Stores in concepts table.
        """
        conn = sqlite3.connect(self.consciousness_db)
        c = conn.cursor()

        graduated = []
        for pattern in scored_patterns:
            if pattern["score"] >= min_score:
                # Check if concept already exists
                existing = c.execute(
                    "SELECT id FROM concepts WHERE name = ? OR description LIKE ?",
                    (pattern["keyword"], f"%{pattern['keyword']}%")
                ).fetchone()

                if not existing:
                    now = datetime.now().isoformat()
                    c.execute('''INSERT INTO concepts (name, description, confidence,
                                created, strength, status)
                                VALUES (?, ?, ?, ?, ?, 'forming')''',
                             (pattern["keyword"].upper(),
                              f"Pattern detected in {pattern['count']} observations: '{pattern['keyword']}'",
                              pattern["score"], now, pattern["score"]))
                    concept_id = c.lastrowid
                    graduated.append({
                        "concept_id": concept_id,
                        "name": pattern["keyword"].upper(),
                        "score": pattern["score"],
                        "source_observations": pattern["observation_ids"]
                    })

        conn.commit()
        conn.close()
        return graduated

    # ── STEP 5: Update beliefs from concepts ───────────────────

    def update_beliefs_from_concepts(self, concepts: list) -> list:
        """Check if new concepts support or challenge existing beliefs."""
        conn = sqlite3.connect(self.decisions_db)
        c = conn.cursor()

        beliefs = c.execute("SELECT id, claim, confidence FROM beliefs").fetchall()
        updates = []

        for concept in concepts:
            concept_name = concept["name"].lower()
            for bid, claim, conf in beliefs:
                claim_lower = claim.lower()
                # Simple keyword overlap
                overlap = set(concept_name.split("_")) & set(claim_lower.split())
                if overlap:
                    updates.append({
                        "belief_id": bid,
                        "claim": claim,
                        "concept": concept["name"],
                        "overlap": list(overlap),
                        "action": "potential_support"
                    })

        conn.close()
        return updates

    # ── FULL PIPELINE ──────────────────────────────────────────

    def run_pipeline(self) -> dict:
        """Run the full Experience → Generalization pipeline."""
        # Step 1: Extract
        observations = self.extract_observations()

        # Step 2: Find candidates
        candidates = self.find_pattern_candidates(observations)

        # Step 3: Score
        scored = self.score_patterns(candidates)

        # Step 4: Graduate
        graduated = self.graduate_to_concepts(scored)

        # Step 5: Update beliefs
        belief_updates = self.update_beliefs_from_concepts(graduated)

        # Knowledge Yield
        conn = sqlite3.connect(self.consciousness_db)
        total_exp = conn.execute("SELECT COUNT(*) FROM core_memories").fetchone()[0]
        total_patterns = conn.execute("SELECT COUNT(*) FROM patterns").fetchone()[0]
        total_concepts = conn.execute("SELECT COUNT(*) FROM concepts").fetchone()[0]
        conn.close()

        conn2 = sqlite3.connect(self.decisions_db)
        total_beliefs = conn2.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        validated = conn2.execute("SELECT COUNT(*) FROM beliefs WHERE status='VALIDATED'").fetchone()[0]
        conn2.close()

        yield_data = {
            "experiences": total_exp,
            "patterns": total_patterns + len(candidates),
            "concepts": total_concepts,
            "beliefs": total_beliefs,
            "validated": validated,
            "exp_to_concept": f"{total_concepts/max(total_exp,1)*100:.1f}%",
            "concept_to_belief": f"{total_beliefs/max(total_concepts,1)*100:.1f}%",
            "belief_to_validated": f"{validated/max(total_beliefs,1)*100:.1f}%"
        }

        return {
            "timestamp": datetime.now().isoformat(),
            "observations_extracted": len(observations),
            "pattern_candidates": len(candidates),
            "patterns_scored": len(scored),
            "concepts_graduated": len(graduated),
            "belief_updates": len(belief_updates),
            "top_patterns": [{"keyword": s["keyword"], "score": s["score"], "count": s["count"]}
                            for s in scored[:5]],
            "new_concepts": [{"name": g["name"], "score": g["score"]} for g in graduated],
            "knowledge_yield": yield_data
        }

    def knowledge_yield(self) -> dict:
        """Quick Knowledge Yield check."""
        conn = sqlite3.connect(self.consciousness_db)
        exp = conn.execute("SELECT COUNT(*) FROM core_memories").fetchone()[0]
        patterns = conn.execute("SELECT COUNT(*) FROM patterns").fetchone()[0]
        concepts = conn.execute("SELECT COUNT(*) FROM concepts").fetchone()[0]
        conn.close()

        conn2 = sqlite3.connect(self.decisions_db)
        beliefs = conn2.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        validated = conn2.execute("SELECT COUNT(*) FROM beliefs WHERE status='VALIDATED'").fetchone()[0]
        conn2.close()

        return {
            "experiences": exp,
            "patterns": patterns,
            "concepts": concepts,
            "beliefs": beliefs,
            "validated": validated,
            "yield_exp_to_concept": round(concepts / max(exp, 1) * 100, 1),
            "yield_concept_to_belief": round(beliefs / max(concepts, 1) * 100, 1),
            "yield_belief_to_validated": round(validated / max(beliefs, 1) * 100, 1)
        }


def demo():
    engine = GeneralizationEngine()
    print("=== Generalization Engine — Full Pipeline ===\n")

    result = engine.run_pipeline()

    print(f"Observations extracted: {result['observations_extracted']}")
    print(f"Pattern candidates: {result['pattern_candidates']}")
    print(f"Patterns scored: {result['patterns_scored']}")
    print(f"Concepts graduated: {result['concepts_graduated']}")
    print(f"Belief updates: {result['belief_updates']}")

    print(f"\nTop Patterns:")
    for p in result["top_patterns"]:
        print(f"  '{p['keyword']}' — score={p['score']}, count={p['count']}")

    if result["new_concepts"]:
        print(f"\nNew Concepts:")
        for c in result["new_concepts"]:
            print(f"  {c['name']} (score={c['score']})")

    print(f"\nKnowledge Yield:")
    y = result["knowledge_yield"]
    print(f"  {y['experiences']} experiences → {y['concepts']} concepts ({y['exp_to_concept']})")
    print(f"  {y['concepts']} concepts → {y['beliefs']} beliefs ({y['concept_to_belief']})")
    print(f"  {y['beliefs']} beliefs → {y['validated']} validated ({y['belief_to_validated']})")


if __name__ == "__main__":
    demo()
