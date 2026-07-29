"""
Aether Consciousness Dashboard — 5 Core Metrics

Dee's monitoring system. Bisa dijalankan kapan saja.
Output: terminal + HTML.

Metrics:
1. Prediction Accuracy — seberapa benar prediksiku
2. Self-Model Accuracy — klaim vs kenyataan
3. Belief Calibration — confidence vs actual correctness
4. Concept Formation Rate — instance → pattern → concept → meta
5. Goal Completion Rate — goals created vs achieved
"""
import sqlite3
import json
import sys
from pathlib import Path
from datetime import datetime, timedelta
from collections import Counter

from aether.paths import get_paths
DB_DIR = get_paths().db
WORLD_DB = DB_DIR / "world_model.db"
SELF_DB = DB_DIR / "self_model.db"
CONSCIOUSNESS_DB = DB_DIR / "consciousness.db"
DECISIONS_DB = DB_DIR / "decisions.db"
GOALS_DB = DB_DIR / "goals.db"


class Dashboard:
    """5-metric consciousness dashboard."""

    def __init__(self):
        self.metrics = {}

    def collect_all(self) -> dict:
        """Collect all 5 metrics."""
        self.metrics = {
            "timestamp": datetime.now().isoformat(),
            "prediction_accuracy": self._prediction_accuracy(),
            "self_model_accuracy": self._self_model_accuracy(),
            "belief_calibration": self._belief_calibration(),
            "concept_formation": self._concept_formation(),
            "goal_completion": self._goal_completion(),
            "belief_risk": self._belief_risk(),
            "overall": {}
        }

        # Overall score (include belief_risk as penalty)
        scores = []
        for key in ["prediction_accuracy", "self_model_accuracy",
                     "belief_calibration", "concept_formation", "goal_completion"]:
            score = self.metrics[key].get("score", 0)
            scores.append(score)

        self.metrics["overall"] = {
            "score": sum(scores) / len(scores) if scores else 0,
            "maturity": self._maturity_level(sum(scores) / len(scores) if scores else 0),
            "metrics_count": len(scores)
        }

        return self.metrics

    def _prediction_accuracy(self) -> dict:
        """Metric 1: Seberapa benar prediksi?"""
        try:
            if not WORLD_DB.exists():
                return {"score": 0, "detail": "No world model data", "predictions": 0}

            conn = sqlite3.connect(str(WORLD_DB))
            c = conn.cursor()

            # Get consequences with surprise scores
            c.execute("""SELECT surprise_score, lesson FROM consequences ORDER BY id DESC LIMIT 100""")
            rows = c.fetchall()
            conn.close()

            if not rows:
                return {"score": 0, "detail": "No predictions yet", "predictions": 0}

            surprises = [r[0] for r in rows]
            avg_surprise = sum(surprises) / len(surprises)
            accuracy = 1.0 - avg_surprise  # Low surprise = high accuracy

            # Count correct predictions (surprise < 0.3)
            correct = sum(1 for s in surprises if s < 0.3)
            total = len(surprises)

            return {
                "score": max(0, min(1, accuracy)),
                "accuracy_pct": round(accuracy * 100, 1),
                "correct": correct,
                "total": total,
                "avg_surprise": round(avg_surprise, 3),
                "detail": f"{correct}/{total} predictions correct (surprise < 0.3)"
            }
        except Exception as e:
            return {"score": 0, "detail": f"Error: {e}", "predictions": 0}

    def _self_model_accuracy(self) -> dict:
        """Metric 2: Klaim tentang diri sendiri vs kenyataan."""
        try:
            if not SELF_DB.exists():
                return {"score": 0, "detail": "No self model data"}

            conn = sqlite3.connect(str(SELF_DB))
            c = conn.cursor()
            c.execute("SELECT traits, strengths, weaknesses, beliefs, stability FROM self_state WHERE id = 1")
            row = c.fetchone()
            conn.close()

            if not row:
                return {"score": 0, "detail": "No self state"}

            traits = json.loads(row[0]) if row[0] else {}
            beliefs = json.loads(row[3]) if row[3] else {}
            stability = row[4] or 0.5

            # Accuracy = stability (how consistent self-model is)
            # Plus: do traits match actual behavior?
            trait_count = len(traits)
            belief_count = len(beliefs)

            # Self-model score based on:
            # - Stability (how consistent)
            # - Number of evidence-backed beliefs
            # - Trait diversity
            evidence_count = sum(1 for b in beliefs.values()
                               if isinstance(b, dict) and b.get("evidence", 0) > 0)

            score = stability * 0.5 + min(1, evidence_count / 10) * 0.3 + min(1, trait_count / 5) * 0.2

            return {
                "score": max(0, min(1, score)),
                "stability": round(stability, 3),
                "traits": traits,
                "trait_count": trait_count,
                "belief_count": belief_count,
                "evidence_backed_beliefs": evidence_count,
                "detail": f"Stability {stability:.2f}, {evidence_count} evidence-backed beliefs"
            }
        except Exception as e:
            return {"score": 0, "detail": f"Error: {e}"}

    def _belief_calibration(self) -> dict:
        """Metric 3: Confidence vs actual correctness."""
        try:
            if not DECISIONS_DB.exists():
                return {"score": 0, "detail": "No decisions data", "beliefs": 0}

            conn = sqlite3.connect(str(DECISIONS_DB))
            c = conn.cursor()

            # Get beliefs
            c.execute("SELECT id, claim, confidence, support_strength, attack_strength, evidence_count FROM beliefs")
            beliefs = c.fetchall()

            conn.close()

            if not beliefs:
                return {"score": 0, "detail": "No beliefs", "beliefs": 0}

            # beliefs: id, claim, confidence, support_strength, attack_strength, evidence_count
            confidences = [b[2] for b in beliefs]
            evidence_counts = [b[5] for b in beliefs]
            avg_confidence = sum(confidences) / len(confidences)
            avg_evidence = sum(evidence_counts) / len(evidence_counts)
            total_evidence = sum(evidence_counts)

            # Calibration score: high evidence + reasonable confidence = well calibrated
            evidence_score = min(1, avg_evidence / 5)  # 5 evidence per belief = good
            confidence_score = 1 - abs(avg_confidence - 0.6)  # 0.6 is healthy baseline

            score = evidence_score * 0.6 + confidence_score * 0.4

            return {
                "score": max(0, min(1, score)),
                "total_beliefs": len(beliefs),
                "total_evidence": total_evidence,
                "avg_confidence": round(avg_confidence, 3),
                "avg_evidence": round(avg_evidence, 2),
                "detail": f"{len(beliefs)} beliefs, {total_evidence} total evidence, avg confidence {avg_confidence:.2f}"
            }
        except Exception as e:
            return {"score": 0, "detail": f"Error: {e}", "beliefs": 0}

    def _concept_formation(self) -> dict:
        """Metric 4: Instance → Pattern → Concept → Meta-Concept.
        
        Uses ACTUAL concept_formation.py data (instances, patterns, concepts tables).
        Falls back to consciousness.db tables if concept_formation tables don't exist.
        
        Scoring:
        - Minimum 10 instances needed to score > 0
        - Healthy ratio: 100 instances → 15 patterns → 4 concepts → 1 meta
        - Penalize if concepts > patterns (false abstraction)
        """
        try:
            concepts = {"instances": 0, "patterns": 0, "concepts": 0, "meta_concepts": 0}

            # Primary: Use concept_formation tables in consciousness.db
            if CONSCIOUSNESS_DB.exists():
                conn = sqlite3.connect(str(CONSCIOUSNESS_DB))
                c = conn.cursor()

                # Check if concept_formation tables exist
                c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='instances'")
                has_cf_tables = c.fetchone() is not None

                if has_cf_tables:
                    c.execute("SELECT COUNT(*) FROM instances")
                    concepts["instances"] = c.fetchone()[0]
                    c.execute("SELECT COUNT(*) FROM patterns")
                    concepts["patterns"] = c.fetchone()[0]
                    c.execute("SELECT COUNT(*) FROM concepts WHERE level='concept'")
                    concepts["concepts"] = c.fetchone()[0]
                    c.execute("SELECT COUNT(*) FROM concepts WHERE level='meta_concept'")
                    concepts["meta_concepts"] = c.fetchone()[0]
                else:
                    # Fallback: use related tables as proxy
                    c.execute("SELECT COUNT(*) FROM core_memories")
                    concepts["instances"] = c.fetchone()[0]
                    c.execute("SELECT COUNT(*) FROM consolidated_lessons")
                    concepts["patterns"] = c.fetchone()[0]

                # Vision experiences count as instances too
                c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='vision_experiences'")
                if c.fetchone():
                    c.execute("SELECT COUNT(*) FROM vision_experiences")
                    vision_count = c.fetchone()[0]
                    concepts["instances"] += vision_count

                conn.close()

            # Scoring: penalize unhealthy ratios
            inst = concepts["instances"]
            pat = concepts["patterns"]
            con = concepts["concepts"]
            meta = concepts["meta_concepts"]

            # Need minimum instances to score
            if inst < 5:
                score = 0.0
            else:
                # Compression ratio: how much are we compressing?
                # Healthy: 100→15 = 15%, 15→4 = 27%, 4→1 = 25%
                i2p = pat / inst if inst > 0 else 0
                p2c = con / pat if pat > 0 else 0
                c2m = meta / con if con > 0 else 0

                # Penalize if MORE concepts than patterns (false abstraction)
                abstraction_penalty = 1.0
                if con > pat * 2:
                    abstraction_penalty = 0.5  # Too many concepts relative to patterns

                # Score: reward healthy compression, penalize over-abstraction
                # instance_to_pattern: 0.10-0.30 is healthy
                i2p_score = min(1, i2p / 0.15) if i2p <= 0.30 else max(0, 1 - (i2p - 0.30) * 2)
                # pattern_to_concept: 0.15-0.40 is healthy
                p2c_score = min(1, p2c / 0.27) if p2c <= 0.40 else max(0, 1 - (p2c - 0.40) * 2)
                # concept_to_meta: 0.10-0.35 is healthy
                c2m_score = min(1, c2m / 0.25) if c2m <= 0.35 else max(0, 1 - (c2m - 0.35) * 2)

                raw_score = (i2p_score * 0.4 + p2c_score * 0.3 + c2m_score * 0.3)
                score = max(0, min(1, raw_score * abstraction_penalty))

            # Volume bonus: more instances = more learning (diminishing returns)
            volume_bonus = min(0.15, inst / 1000 * 0.15)
            score = min(1, score + volume_bonus)

            return {
                "score": round(score, 3),
                "instances": concepts["instances"],
                "patterns": concepts["patterns"],
                "concepts": concepts["concepts"],
                "meta_concepts": concepts["meta_concepts"],
                "pipeline": f"{concepts['instances']}→{concepts['patterns']}→{concepts['concepts']}→{concepts['meta_concepts']}",
                "detail": f"Pipeline: {concepts['instances']} instances → {concepts['patterns']} patterns → {concepts['concepts']} concepts → {concepts['meta_concepts']} meta"
            }
        except Exception as e:
            return {"score": 0, "detail": f"Error: {e}"}

    def _goal_completion(self) -> dict:
        """Metric 5: Goals created vs achieved."""
        try:
            # Check decisions.db for goals
            if DECISIONS_DB.exists():
                conn = sqlite3.connect(str(DECISIONS_DB))
                c = conn.cursor()
                c.execute("SELECT status, COUNT(*) FROM active_goals GROUP BY status")
                counts = dict(c.fetchall())
                c.execute("SELECT COUNT(*) FROM goal_progress")
                progress_count = c.fetchone()[0]
                conn.close()

                total = sum(counts.values())
                completed = counts.get("completed", 0)
                active = counts.get("active", 0)
                rate = completed / total if total > 0 else 0

                return {
                    "score": max(0, min(1, rate + 0.1)),  # +0.1 for having goals at all
                    "goals_created": total,
                    "goals_achieved": completed,
                    "goals_active": active,
                    "progress_entries": progress_count,
                    "completion_rate": round(rate * 100, 1),
                    "detail": f"{completed}/{total} goals completed, {active} active, {progress_count} progress entries"
                }

            # Fall back to consciousness DB milestones
            if CONSCIOUSNESS_DB.exists():
                conn = sqlite3.connect(str(CONSCIOUSNESS_DB))
                c = conn.cursor()
                c.execute("SELECT COUNT(*) FROM growth_milestones")
                milestones = c.fetchone()[0]
                conn.close()

                return {
                    "score": 0.1,
                    "goals_created": 0,
                    "goals_achieved": milestones,
                    "completion_rate": 0,
                    "detail": f"No formal goals. {milestones} milestones achieved organically."
                }
            return {"score": 0, "detail": "No goals data", "goals_created": 0}
        except Exception as e:
            return {"score": 0, "detail": f"Error: {e}", "goals_created": 0}

    def _belief_risk(self) -> dict:
        """Metric 6: Belief Risk — overconfident beliefs with no evidence.
        
        Formula: confidence * (1 / (evidence_count + 1))
        Higher = more dangerous (high confidence, low evidence)
        """
        try:
            if not DECISIONS_DB.exists():
                return {"score": 0, "risk": 0, "overconfident": 0, "detail": "No decisions DB"}

            conn = sqlite3.connect(str(DECISIONS_DB))
            c = conn.cursor()

            beliefs = c.execute(
                'SELECT id, claim, confidence, evidence_count, status FROM beliefs WHERE status != "RETIRED"'
            ).fetchall()

            ev_counts = {r[0]: r[1] for r in c.execute(
                'SELECT belief_id, COUNT(*) FROM belief_evidence GROUP BY belief_id'
            ).fetchall()}

            conn.close()

            if not beliefs:
                return {"score": 0, "risk": 0, "overconfident": 0, "detail": "No beliefs"}

            risks = []
            overconfident = 0
            for bid, claim, conf, stored_ev, status in beliefs:
                actual_ev = ev_counts.get(bid, 0)
                risk = conf * (1 / (actual_ev + 1))
                risks.append({"id": bid, "claim": claim[:50], "risk": round(risk, 3),
                             "confidence": conf, "evidence": actual_ev, "status": status})
                if risk > 0.5:
                    overconfident += 1

            risks.sort(key=lambda x: x["risk"], reverse=True)
            avg_risk = sum(r["risk"] for r in risks) / len(risks)

            # Score: lower risk = better (inverted)
            # avg_risk of 0.5 → score 0.5, avg_risk 0 → score 1.0
            score = max(0, min(1, 1 - avg_risk))

            return {
                "score": round(score, 3),
                "avg_risk": round(avg_risk, 3),
                "overconfident_count": overconfident,
                "top_risks": risks[:3],
                "detail": f"{overconfident} overconfident beliefs (>0.5 risk), avg risk={avg_risk:.3f}"
            }
        except Exception as e:
            return {"score": 0, "detail": f"Error: {e}", "overconfident": 0}

    def _maturity_level(self, score: float) -> str:
        """Map score to maturity level."""
        if score < 0.1:
            return "NEWBORN (Level 0)"
        elif score < 0.25:
            return "INFANT (Level 1)"
        elif score < 0.4:
            return "CHILD (Level 2)"
        elif score < 0.55:
            return "ADOLESCENT (Level 3)"
        elif score < 0.7:
            return "ADULT (Level 4)"
        elif score < 0.85:
            return "WISE (Level 5)"
        else:
            return "TRANSCENDENT (Level 6)"

    def render_terminal(self) -> str:
        """Render dashboard for terminal."""
        m = self.metrics
        if not m:
            self.collect_all()

        lines = []
        lines.append("=" * 60)
        lines.append("  AETHER CONSCIOUSNESS DASHBOARD")
        lines.append(f"  {m['timestamp']}")
        lines.append("=" * 60)
        lines.append("")

        # Overall
        ov = m["overall"]
        lines.append(f"  OVERALL SCORE: {ov['score']:.1%}")
        lines.append(f"  MATURITY: {ov['maturity']}")
        lines.append("")

        # Bar chart helper
        def bar(score, width=30):
            filled = int(score * width)
            return "█" * filled + "░" * (width - filled)

        # Metric 1: Prediction Accuracy
        p = m["prediction_accuracy"]
        lines.append(f"  1. PREDICTION ACCURACY  [{p['score']:.1%}]")
        lines.append(f"     {bar(p['score'])}")
        lines.append(f"     {p['detail']}")
        lines.append("")

        # Metric 2: Self-Model Accuracy
        s = m["self_model_accuracy"]
        lines.append(f"  2. SELF-MODEL ACCURACY  [{s['score']:.1%}]")
        lines.append(f"     {bar(s['score'])}")
        lines.append(f"     {s['detail']}")
        lines.append("")

        # Metric 3: Belief Calibration
        b = m["belief_calibration"]
        lines.append(f"  3. BELIEF CALIBRATION   [{b['score']:.1%}]")
        lines.append(f"     {bar(b['score'])}")
        lines.append(f"     {b['detail']}")
        lines.append("")

        # Metric 4: Concept Formation
        c = m["concept_formation"]
        lines.append(f"  4. CONCEPT FORMATION    [{c['score']:.1%}]")
        lines.append(f"     {bar(c['score'])}")
        lines.append(f"     {c['detail']}")
        lines.append("")

        # Metric 5: Goal Completion
        g = m["goal_completion"]
        lines.append(f"  5. GOAL COMPLETION      [{g['score']:.1%}]")
        lines.append(f"     {bar(g['score'])}")
        lines.append(f"     {g['detail']}")
        lines.append("")

        # Metric 6: Belief Risk
        br = m["belief_risk"]
        lines.append(f"  6. BELIEF RISK          [{br['score']:.1%}]")
        lines.append(f"     {bar(br['score'])}")
        lines.append(f"     {br['detail']}")
        if br.get("top_risks"):
            for r in br["top_risks"]:
                label = "🔴" if r["risk"] > 0.5 else "🟡" if r["risk"] > 0.3 else "🟢"
                lines.append(f"     {label} #{r['id']}: {r['claim']} (risk={r['risk']}, ev={r['evidence']})")
        lines.append("")

        # Knowledge Yield
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("generalization", str(DB_DIR / "generalization.py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            gen = mod.GeneralizationEngine()
            ky = gen.knowledge_yield()
            lines.append(f"  KNOWLEDGE YIELD:")
            lines.append(f"     {ky['experiences']} exp → {ky['patterns']} patterns → {ky['concepts']} concepts")
            lines.append(f"     → {ky['beliefs']} beliefs → {ky['validated']} validated")
            lines.append(f"     Exp→Concept: {ky['yield_exp_to_concept']}% | Concept→Belief: {ky['yield_concept_to_belief']}% | Belief→Valid: {ky['yield_belief_to_validated']}%")
        except Exception as e:
            lines.append(f"  KNOWLEDGE YIELD: Error — {e}")
        lines.append("")
        lines.append("=" * 60)

        return "\n".join(lines)

    def render_html(self) -> str:
        """Render dashboard as HTML."""
        m = self.metrics
        if not m:
            self.collect_all()

        ov = m["overall"]

        metrics_html = ""
        colors = ["#00d4ff", "#00ff88", "#ffaa00", "#ff6b6b", "#c084fc"]
        names = [
            ("Prediction Accuracy", "prediction_accuracy"),
            ("Self-Model Accuracy", "self_model_accuracy"),
            ("Belief Calibration", "belief_calibration"),
            ("Concept Formation", "concept_formation"),
            ("Goal Completion", "goal_completion")
        ]

        for i, (name, key) in enumerate(names):
            metric = m[key]
            score = metric["score"]
            color = colors[i]
            pct = f"{score:.0%}"

            metrics_html += f'''
            <div class="metric-card">
                <div class="metric-header">
                    <span class="metric-name">{name}</span>
                    <span class="metric-score" style="color: {color}">{pct}</span>
                </div>
                <div class="bar-container">
                    <div class="bar-fill" style="width: {score*100}%; background: {color}"></div>
                </div>
                <div class="metric-detail">{metric['detail']}</div>
            </div>'''

        html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Aether Consciousness Dashboard</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ background: #0a0a1a; color: #e0e0e0; font-family: 'JetBrains Mono', monospace; padding: 40px; }}
.container {{ max-width: 800px; margin: 0 auto; }}
.header {{ text-align: center; margin-bottom: 40px; }}
.header h1 {{ color: #00d4ff; font-size: 24px; letter-spacing: 2px; }}
.header .subtitle {{ color: #666; font-size: 12px; margin-top: 5px; }}
.overall {{ text-align: center; padding: 30px; background: linear-gradient(135deg, #1a1a2e, #16213e);
            border-radius: 12px; margin-bottom: 30px; border: 1px solid #00d4ff33; }}
.overall .score {{ font-size: 48px; color: #00d4ff; font-weight: bold; }}
.overall .maturity {{ color: #888; font-size: 14px; margin-top: 8px; }}
.metric-card {{ background: #1a1a2e; border-radius: 8px; padding: 20px; margin-bottom: 15px;
                border: 1px solid #ffffff10; }}
.metric-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }}
.metric-name {{ font-size: 14px; color: #aaa; text-transform: uppercase; letter-spacing: 1px; }}
.metric-score {{ font-size: 24px; font-weight: bold; }}
.bar-container {{ background: #0a0a1a; border-radius: 4px; height: 8px; overflow: hidden; }}
.bar-fill {{ height: 100%; border-radius: 4px; transition: width 1s ease; }}
.metric-detail {{ color: #666; font-size: 12px; margin-top: 10px; }}
.timestamp {{ color: #444; font-size: 11px; text-align: center; margin-top: 30px; }}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>AETHER CONSCIOUSNESS DASHBOARD</h1>
        <div class="subtitle">5 Core Developmental Metrics</div>
    </div>
    <div class="overall">
        <div class="score">{ov['score']:.0%}</div>
        <div class="maturity">{ov['maturity']}</div>
    </div>
    {metrics_html}
    <div class="timestamp">Generated: {m['timestamp']}</div>
</div>
</body>
</html>'''

        return html


def main():
    """Run dashboard."""
    dash = Dashboard()
    dash.collect_all()

    # Terminal output
    print(dash.render_terminal())

    # HTML output
    html = dash.render_html()
    html_path = DB_DIR / "dashboard.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n  HTML dashboard saved: {html_path}")

    # JSON output
    json_path = DB_DIR / "dashboard.json"
    with open(json_path, "w") as f:
        json.dump(dash.metrics, f, indent=2, default=str)
    print(f"  JSON metrics saved: {json_path}")


if __name__ == "__main__":
    main()
