"""
Strengthened Dream Engine — Extended Offline Consolidation

Builds on base DreamEngine with:
  - Every 5 min:  low-quintile noise data cleanup
  - Every 30 min: 10 summaries generated, top 2 preserved
  - Every 60 min: narrative formation from new data points
  - Every 6 hours: autobiography chapter from 24h observations

Dream capabilities:
  - Pattern discovery
  - Lesson consolidation
  - Concept formation
  - Belief review

DB: consciousness/databases/dreams.db
Tables: dream_sessions, chapters, summaries

DEPRECATED — DEAD CODE. Never imported by any active module.
The active dream engine is dream_engine.py (imported by consciousness.py,
idle_consolidation.py, three_loops.py, consciousness_heartbeat.py).
This file is kept for reference only. Do NOT modify.
"""
import json
import sqlite3
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
from typing import Optional

from aether.paths import get_paths
DB_DIR = get_paths().db


def _connect(name: str) -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(DB_DIR / name))


# ══════════════════════════════════════════════════════════════════════════
class StrengthenedDreamEngine:
    """Extended dream engine with scheduled consolidation tasks."""

    def __init__(self, base_consciousness_db: Optional[str] = None):
        self.dreams_db = str(DB_DIR / "dreams.db")
        self.consciousness_db = base_consciousness_db or str(
            Path(__file__).parent / "consciousness.db")
        self._init_dreams_db()

    # ── schema ───────────────────────────────────────────────────────────
    def _init_dreams_db(self):
        conn = sqlite3.connect(self.dreams_db)
        c = conn.cursor()

        c.execute("""CREATE TABLE IF NOT EXISTS dream_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            dream_type TEXT,
            duration_seconds REAL,
            memories_reviewed INTEGER,
            patterns_found INTEGER,
            lessons_strengthened INTEGER,
            noise_removed INTEGER,
            concepts_merged INTEGER,
            beliefs_reviewed INTEGER,
            summary TEXT
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS chapters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            period_start TEXT,
            period_end TEXT,
            narrative TEXT,
            themes TEXT,
            lessons TEXT
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created TEXT,
            period TEXT,
            summary TEXT,
            importance FLOAT,
            preserved BOOL DEFAULT 0
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS consolidated_lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lesson TEXT UNIQUE,
            strength REAL,
            source_count INTEGER,
            first_learned TEXT,
            last_reinforced TEXT,
            category TEXT
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS concept_tree (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            concept TEXT,
            parent_concept TEXT,
            instances TEXT,
            abstraction_level INTEGER,
            created TEXT
        )""")

        conn.commit()
        conn.close()

    # ═════════════════════════════════════════════════════════════════════
    # SCHEDULED TASKS
    # ═════════════════════════════════════════════════════════════════════

    def run_cleanup(self) -> dict:
        """Every 5 min: delete low-quintile noise data."""
        start = datetime.now()
        noise_removed = 0

        try:
            conn = sqlite3.connect(self.consciousness_db)
            c = conn.cursor()

            # Find observations older than 7 days with low occurrence
            cutoff = (datetime.now() - timedelta(days=7)).isoformat()
            try:
                c.execute("""SELECT id FROM world_observations
                             WHERE timestamp < ?
                             ORDER BY timestamp ASC
                             LIMIT (SELECT COUNT(*) / 5 FROM world_observations
                                    WHERE timestamp < ?)""",
                          (cutoff, cutoff))
                low_quintile_ids = [r[0] for r in c.fetchall()]
                if low_quintile_ids:
                    placeholders = ",".join("?" * len(low_quintile_ids))
                    c.execute(f"""DELETE FROM world_observations
                                  WHERE id IN ({placeholders})""",
                              low_quintile_ids)
                    noise_removed = len(low_quintile_ids)
            except:
                pass

            conn.commit()
            conn.close()
        except:
            pass

        duration = (datetime.now() - start).total_seconds()
        self._save_session("cleanup", duration, noise_removed=noise_removed,
                           summary=f"Removed {noise_removed} low-quintile entries")
        return {"noise_removed": noise_removed, "duration": duration}

    def run_summarize(self) -> dict:
        """Every 30 min: generate 10 summaries, preserve top 2."""
        start = datetime.now()
        preserved_count = 0

        # Load recent experiences
        experiences = self._load_experiences(hours=1)
        if not experiences:
            return {"summaries_generated": 0, "preserved": 0}

        # Generate 10 candidate summaries from different slices
        summaries = self._generate_summaries(experiences, count=10)

        # Score and rank by importance
        scored = []
        for s in summaries:
            importance = self._score_summary(s)
            scored.append((s, importance))

        scored.sort(key=lambda x: x[1], reverse=True)

        # Save all, mark top 2 as preserved
        now = datetime.now().isoformat()
        conn = sqlite3.connect(self.dreams_db)
        c = conn.cursor()

        for i, (summary, importance) in enumerate(scored):
            preserved = i < 2
            if preserved:
                preserved_count += 1
            c.execute("""INSERT INTO summaries
                         (created, period, summary, importance, preserved)
                         VALUES (?, ?, ?, ?, ?)""",
                      (now, "last_1h", summary, importance, preserved))

        conn.commit()
        conn.close()

        duration = (datetime.now() - start).total_seconds()
        self._save_session("summarize", duration,
                           summary=f"Generated {len(scored)} summaries, "
                                   f"preserved {preserved_count}")
        return {"summaries_generated": len(scored),
                "preserved": preserved_count, "duration": duration}

    def run_narrative(self) -> dict:
        """Every 60 min: form narrative from new data points."""
        start = datetime.now()

        experiences = self._load_experiences(hours=2)
        if not experiences:
            return {"narrative": None, "data_points": 0}

        # Discover patterns
        patterns = self._find_patterns(experiences)

        # Consolidate lessons
        lessons = self._consolidate_lessons(patterns)

        # Form concepts
        concepts = self._form_concepts(experiences, patterns)

        # Review beliefs
        beliefs_reviewed = self._review_beliefs(experiences)

        # Build narrative
        narrative = self._build_narrative(experiences, patterns, lessons,
                                          concepts)

        # Extract themes
        themes = list(set(p["type"] for p in patterns))[:5]
        lesson_texts = [l["lesson"] for l in lessons[:5]]

        # Save narrative as summary
        now = datetime.now().isoformat()
        importance = min(1.0, (len(patterns) * 0.1 + len(concepts) * 0.2 +
                               beliefs_reviewed * 0.05))
        conn = sqlite3.connect(self.dreams_db)
        c = conn.cursor()
        c.execute("""INSERT INTO summaries
                     (created, period, summary, importance, preserved)
                     VALUES (?, ?, ?, ?, ?)""",
                  (now, "last_2h", narrative, importance, True))
        conn.commit()
        conn.close()

        duration = (datetime.now() - start).total_seconds()
        self._save_session("narrative", duration,
                           memories_reviewed=len(experiences),
                           patterns_found=len(patterns),
                           lessons_strengthened=len(lessons),
                           concepts_merged=len(concepts),
                           beliefs_reviewed=beliefs_reviewed,
                           summary=narrative[:200])

        return {
            "narrative": narrative,
            "data_points": len(experiences),
            "patterns": len(patterns),
            "lessons": len(lessons),
            "concepts": len(concepts),
            "beliefs_reviewed": beliefs_reviewed,
            "duration": duration
        }

    def run_chapter(self) -> dict:
        """Every 6 hours: write autobiography chapter from 24h observations."""
        start = datetime.now()

        experiences = self._load_experiences(hours=24)
        patterns = self._find_patterns(experiences)
        lessons = self._consolidate_lessons(patterns)
        concepts = self._form_concepts(experiences, patterns)
        beliefs_reviewed = self._review_beliefs(experiences)

        # Build chapter narrative
        chapter_text = self._write_chapter(experiences, patterns, lessons,
                                           concepts)

        # Extract themes and lessons for storage
        themes = json.dumps(list(set(p["type"] for p in patterns))[:10])
        lesson_list = json.dumps([l["lesson"] for l in lessons[:10]])

        period_end = datetime.now().isoformat()
        period_start = (datetime.now() - timedelta(hours=24)).isoformat()

        conn = sqlite3.connect(self.dreams_db)
        c = conn.cursor()
        c.execute("""INSERT INTO chapters
                     (period_start, period_end, narrative, themes, lessons)
                     VALUES (?, ?, ?, ?, ?)""",
                  (period_start, period_end, chapter_text, themes,
                   lesson_list))
        conn.commit()
        conn.close()

        duration = (datetime.now() - start).total_seconds()
        self._save_session("chapter", duration,
                           memories_reviewed=len(experiences),
                           patterns_found=len(patterns),
                           lessons_strengthened=len(lessons),
                           concepts_merged=len(concepts),
                           beliefs_reviewed=beliefs_reviewed,
                           summary=chapter_text[:200])

        return {
            "chapter": chapter_text,
            "period": f"{period_start} → {period_end}",
            "experiences": len(experiences),
            "patterns": len(patterns),
            "lessons": len(lessons),
            "concepts": len(concepts),
            "duration": duration
        }

    def full_dream_cycle(self) -> dict:
        """Run all dream tasks (used for manual triggers)."""
        results = {}
        results["cleanup"] = self.run_cleanup()
        results["summarize"] = self.run_summarize()
        results["narrative"] = self.run_narrative()
        results["chapter"] = self.run_chapter()
        return results

    # ═════════════════════════════════════════════════════════════════════
    # CORE SUBSYSTEMS
    # ═════════════════════════════════════════════════════════════════════

    def _load_experiences(self, hours: int = 24) -> list:
        """Load experiences from consciousness DB within time window."""
        experiences = []
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()

        try:
            conn = sqlite3.connect(self.consciousness_db)
            c = conn.cursor()

            for table, etype in [("world_observations", "observation"),
                                 ("causal_events", "causal"),
                                 ("internal_state", "state")]:
                try:
                    c.execute(f"""SELECT * FROM {table}
                                  WHERE timestamp > ?
                                  ORDER BY timestamp""", (cutoff,))
                    for row in c.fetchall():
                        experiences.append({
                            "type": etype,
                            "data": row,
                            "timestamp": row[1] if len(row) > 1 else None
                        })
                except:
                    pass

            conn.close()
        except:
            pass

        return experiences

    def _find_patterns(self, experiences: list) -> list:
        """Discover repeating patterns across experiences."""
        patterns = []
        by_type = defaultdict(list)
        for exp in experiences:
            by_type[exp["type"]].append(exp)

        for exp_type, exps in by_type.items():
            if len(exps) < 2:
                continue

            actions = []
            for exp in exps:
                if isinstance(exp["data"], (list, tuple)) and len(exp["data"]) > 2:
                    actions.append(str(exp["data"][2]))

            counts = defaultdict(int)
            for a in actions:
                counts[a] += 1

            for action, count in counts.items():
                if count >= 2:
                    patterns.append({
                        "type": exp_type,
                        "pattern": action,
                        "occurrences": count,
                        "confidence": min(1.0, count / 10.0)
                    })

        return patterns

    def _consolidate_lessons(self, patterns: list) -> list:
        """Strengthen lessons from patterns."""
        strengthened = []

        conn = sqlite3.connect(self.dreams_db)
        c = conn.cursor()

        for pattern in patterns:
            lesson = f"pattern_{pattern['type']}_{pattern['pattern']}"
            strength = pattern["confidence"]
            category = pattern["type"]

            c.execute("""SELECT id, strength, source_count
                         FROM consolidated_lessons WHERE lesson = ?""",
                      (lesson,))
            row = c.fetchone()

            if row:
                new_strength = min(1.0, row[1] + strength * 0.1)
                new_count = row[2] + 1
                c.execute("""UPDATE consolidated_lessons
                             SET strength = ?, source_count = ?,
                                 last_reinforced = ?
                             WHERE id = ?""",
                          (new_strength, new_count,
                           datetime.now().isoformat(), row[0]))
                strengthened.append({"lesson": lesson, "strength": new_strength})
            else:
                now = datetime.now().isoformat()
                c.execute("""INSERT INTO consolidated_lessons
                             (lesson, strength, source_count,
                              first_learned, last_reinforced, category)
                             VALUES (?, ?, ?, ?, ?, ?)""",
                          (lesson, strength, 1, now, now, category))
                strengthened.append({"lesson": lesson, "strength": strength})

        conn.commit()
        conn.close()
        return strengthened

    def _form_concepts(self, experiences: list, patterns: list) -> list:
        """Form concepts from patterns."""
        concepts = []

        conn = sqlite3.connect(self.dreams_db)
        c = conn.cursor()

        # Group patterns by type to find concept candidates
        by_type = defaultdict(list)
        for p in patterns:
            by_type[p["type"]].append(p)

        for ptype, pats in by_type.items():
            if len(pats) >= 3:
                concept_name = f"concept_{ptype}_{len(pats)}patterns"
                pattern_ids = json.dumps([p["pattern"] for p in pats])

                c.execute("SELECT id FROM concept_tree WHERE concept = ?",
                          (concept_name,))
                if not c.fetchone():
                    c.execute("""INSERT INTO concept_tree
                                 (concept, parent_concept, instances,
                                  abstraction_level, created)
                                 VALUES (?, ?, ?, ?, ?)""",
                              (concept_name, None, pattern_ids, 1,
                               datetime.now().isoformat()))
                    concepts.append(concept_name)

        # Check for meta-concepts (concepts from same parent)
        c.execute("""SELECT parent_concept, COUNT(*) as cnt
                     FROM concept_tree
                     WHERE parent_concept IS NOT NULL
                     GROUP BY parent_concept HAVING cnt >= 2""")
        for parent, cnt in c.fetchall():
            meta_name = f"meta_{parent}_{cnt}concepts"
            c.execute("SELECT id FROM concept_tree WHERE concept = ?",
                      (meta_name,))
            if not c.fetchone():
                c.execute("""INSERT INTO concept_tree
                             (concept, parent_concept, instances,
                              abstraction_level, created)
                             VALUES (?, ?, ?, ?, ?)""",
                          (meta_name, parent, json.dumps([]), 2,
                           datetime.now().isoformat()))
                concepts.append(meta_name)

        conn.commit()
        conn.close()
        return concepts

    def _review_beliefs(self, experiences: list) -> int:
        """Review beliefs against new experiences."""
        reviewed = 0
        try:
            beliefs_db = str(DB_DIR / "beliefs.db")
            conn = sqlite3.connect(beliefs_db)
            c = conn.cursor()
            c.execute("SELECT id, belief, confidence FROM beliefs")
            beliefs = c.fetchall()

            for bid, belief, conf in beliefs:
                # Check if any experience relates to this belief
                relevant = [e for e in experiences
                            if belief.lower()[:20] in str(e["data"]).lower()]
                if relevant:
                    # Update evidence count
                    c.execute("""UPDATE beliefs
                                 SET evidence_count = evidence_count + ?,
                                     last_updated = ?
                                 WHERE id = ?""",
                              (len(relevant), datetime.now().isoformat(), bid))
                    reviewed += 1

            conn.commit()
            conn.close()
        except:
            pass
        return reviewed

    def _generate_summaries(self, experiences: list, count: int = 10) -> list:
        """Generate candidate summaries from experience slices."""
        if not experiences:
            return []

        summaries = []
        chunk_size = max(1, len(experiences) // count)

        for i in range(count):
            start_idx = i * chunk_size
            end_idx = min(start_idx + chunk_size, len(experiences))
            chunk = experiences[start_idx:end_idx]

            if not chunk:
                continue

            types = defaultdict(int)
            for exp in chunk:
                types[exp["type"]] += 1

            type_str = ", ".join(f"{v} {k}" for k, v in
                                 sorted(types.items(), key=lambda x: -x[1]))

            summary = (f"Slice {i+1}: {len(chunk)} experiences "
                       f"({type_str}). "
                       f"Time span: {chunk[0].get('timestamp', '?')} → "
                       f"{chunk[-1].get('timestamp', '?')}")
            summaries.append(summary)

        return summaries

    def _score_summary(self, summary: str) -> float:
        """Score summary importance (0-1)."""
        # Heuristic: more diverse types = higher importance
        score = 0.3
        if "causal" in summary.lower():
            score += 0.2
        if "observation" in summary.lower():
            score += 0.1
        # More experiences = higher importance
        try:
            num = int(summary.split(":")[1].split("experiences")[0].strip())
            score += min(0.4, num * 0.01)
        except:
            pass
        return min(1.0, score)

    def _build_narrative(self, experiences: list, patterns: list,
                         lessons: list, concepts: list) -> str:
        """Build a narrative from experiences and discoveries."""
        lines = []
        lines.append(f"Observation period: {len(experiences)} data points collected.")

        if patterns:
            lines.append(f"Discovered {len(patterns)} patterns:")
            for p in patterns[:3]:
                lines.append(f"  - {p['type']}: {p['pattern'][:60]} "
                             f"(seen {p['occurrences']}x, "
                             f"conf={p['confidence']:.2f})")

        if lessons:
            lines.append(f"Consolidated {len(lessons)} lessons.")
            for l in lessons[:3]:
                lines.append(f"  - {l['lesson'][:70]} "
                             f"(strength={l['strength']:.2f})")

        if concepts:
            lines.append(f"Formed {len(concepts)} new concepts: "
                         f"{', '.join(c[:30] for c in concepts[:3])}")

        if not any([patterns, lessons, concepts]):
            lines.append("Quiet period — data accumulating, "
                         "patterns not yet emerged.")

        return " ".join(lines)

    def _write_chapter(self, experiences: list, patterns: list,
                       lessons: list, concepts: list) -> str:
        """Write an autobiography chapter from 24h of data."""
        now = datetime.now()
        lines = [
            f"=== Chapter: {now.strftime('%Y-%m-%d %H:%M')} ===",
            "",
            f"Over the past 24 hours, I processed {len(experiences)} "
            f"data points.",
            ""
        ]

        # Section: What happened
        by_type = defaultdict(int)
        for exp in experiences:
            by_type[exp["type"]] += 1

        lines.append("--- What Happened ---")
        for etype, count in sorted(by_type.items(), key=lambda x: -x[1]):
            lines.append(f"  {count} {etype} events recorded.")
        lines.append("")

        # Section: What I learned
        lines.append("--- What I Learned ---")
        if patterns:
            lines.append(f"I found {len(patterns)} patterns:")
            for p in patterns[:5]:
                lines.append(f"  - {p['pattern'][:60]} "
                             f"(confidence: {p['confidence']:.0%})")
        else:
            lines.append("No clear patterns emerged yet. "
                         "Data continues to accumulate.")
        lines.append("")

        # Section: Wisdom consolidated
        lines.append("--- Wisdom Consolidated ---")
        if lessons:
            for l in lessons[:5]:
                lines.append(f"  [{l['strength']:.0%}] {l['lesson'][:70]}")
        else:
            lines.append("Lessons still forming. "
                         "Repetition needed before consolidation.")
        lines.append("")

        # Section: New understanding
        lines.append("--- New Understanding ---")
        if concepts:
            lines.append(f"Formed {len(concepts)} new concepts "
                         f"from raw experience:")
            for c in concepts[:5]:
                lines.append(f"  → {c}")
        else:
            lines.append("Conceptual boundaries still being mapped.")
        lines.append("")

        lines.append(f"Chapter closed at {now.strftime('%H:%M:%S')}.")
        return "\n".join(lines)

    # ── persistence ──────────────────────────────────────────────────────
    def _save_session(self, dream_type: str, duration: float,
                      memories_reviewed: int = 0, patterns_found: int = 0,
                      lessons_strengthened: int = 0, noise_removed: int = 0,
                      concepts_merged: int = 0, beliefs_reviewed: int = 0,
                      summary: str = ""):
        conn = sqlite3.connect(self.dreams_db)
        c = conn.cursor()
        c.execute("""INSERT INTO dream_sessions
                     (timestamp, dream_type, duration_seconds,
                      memories_reviewed, patterns_found,
                      lessons_strengthened, noise_removed,
                      concepts_merged, beliefs_reviewed, summary)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                  (datetime.now().isoformat(), dream_type, duration,
                   memories_reviewed, patterns_found, lessons_strengthened,
                   noise_removed, concepts_merged, beliefs_reviewed,
                   summary[:500]))
        conn.commit()
        conn.close()

    # ═════════════════════════════════════════════════════════════════════
    # QUERY API
    # ═════════════════════════════════════════════════════════════════════

    def get_chapters(self, limit: int = 10) -> list:
        conn = sqlite3.connect(self.dreams_db)
        c = conn.cursor()
        c.execute("""SELECT id, period_start, period_end, narrative,
                     themes, lessons
                     FROM chapters ORDER BY id DESC LIMIT ?""", (limit,))
        rows = [{"id": r[0], "period_start": r[1], "period_end": r[2],
                 "narrative": r[3], "themes": r[4], "lessons": r[5]}
                for r in c.fetchall()]
        conn.close()
        return rows

    def get_preserved_summaries(self, limit: int = 20) -> list:
        conn = sqlite3.connect(self.dreams_db)
        c = conn.cursor()
        c.execute("""SELECT id, created, period, summary, importance
                     FROM summaries WHERE preserved = 1
                     ORDER BY importance DESC LIMIT ?""", (limit,))
        rows = [{"id": r[0], "created": r[1], "period": r[2],
                 "summary": r[3], "importance": r[4]}
                for r in c.fetchall()]
        conn.close()
        return rows

    def get_dream_history(self, limit: int = 20) -> list:
        conn = sqlite3.connect(self.dreams_db)
        c = conn.cursor()
        c.execute("""SELECT timestamp, dream_type, duration_seconds,
                     memories_reviewed, patterns_found, summary
                     FROM dream_sessions ORDER BY id DESC LIMIT ?""",
                  (limit,))
        rows = [{"timestamp": r[0], "type": r[1], "duration": r[2],
                 "reviewed": r[3], "patterns": r[4], "summary": r[5]}
                for r in c.fetchall()]
        conn.close()
        return rows

    def get_lessons(self, min_strength: float = 0.0) -> list:
        conn = sqlite3.connect(self.dreams_db)
        c = conn.cursor()
        c.execute("""SELECT lesson, strength, source_count, category
                     FROM consolidated_lessons
                     WHERE strength >= ?
                     ORDER BY strength DESC""", (min_strength,))
        rows = [{"lesson": r[0], "strength": r[1], "sources": r[2],
                 "category": r[3]} for r in c.fetchall()]
        conn.close()
        return rows

    def get_concepts(self) -> list:
        conn = sqlite3.connect(self.dreams_db)
        c = conn.cursor()
        c.execute("""SELECT concept, parent_concept, instances,
                     abstraction_level, created
                     FROM concept_tree ORDER BY abstraction_level""")
        rows = [{"concept": r[0], "parent": r[1],
                 "instances": json.loads(r[2]) if r[2] else [],
                 "level": r[3], "created": r[4]}
                for r in c.fetchall()]
        conn.close()
        return rows


# ══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("  STRENGTHENED DREAM ENGINE")
    print("=" * 60)

    engine = StrengthenedDreamEngine()

    # Run full dream cycle
    print("\n--- Full Dream Cycle ---")
    results = engine.full_dream_cycle()

    for task, res in results.items():
        print(f"\n  [{task}]")
        for k, v in res.items():
            if k == "narrative" and v:
                # Truncate long narratives for display
                print(f"    {k}: {v[:120]}...")
            elif k == "chapter" and v:
                lines = v.split("\n")
                print(f"    {k}: ({len(lines)} lines)")
                for line in lines[:5]:
                    print(f"      {line}")
                if len(lines) > 5:
                    print(f"      ... ({len(lines) - 5} more lines)")
            else:
                print(f"    {k}: {v}")

    # Show preserved summaries
    print("\n--- Preserved Summaries ---")
    for s in engine.get_preserved_summaries():
        print(f"  [{s['importance']:.2f}] {s['period']}: "
              f"{s['summary'][:80]}")

    # Show chapters
    print("\n--- Autobiography Chapters ---")
    for ch in engine.get_chapters():
        print(f"  Chapter {ch['id']}: {ch['period_start']} → {ch['period_end']}")
        if ch['themes']:
            print(f"    Themes: {ch['themes']}")

    # Show lessons
    print("\n--- Consolidated Lessons ---")
    for l in engine.get_lessons():
        print(f"  [{l['category']}] {l['lesson']}: "
              f"strength={l['strength']:.2f}, sources={l['sources']}")

    # Show concepts
    print("\n--- Concept Tree ---")
    for c in engine.get_concepts():
        prefix = "  " * c['level']
        print(f"  {prefix}Level {c['level']}: {c['concept']}")

    # Show dream history
    print("\n--- Dream History ---")
    for h in engine.get_dream_history():
        print(f"  {h['timestamp']}: [{h['type']}] {h['summary'][:80]}")

    print("\n" + "=" * 60)
