"""
aether_core.py — Aether v0: World Model + Causality + Prediction
================================================================

Filosofi: Bayi tidak lahir dengan pengetahuan.
Bayi lahir dengan kemampuan membentuk model dunia.

Primitives: Object, State, Action, Consequence
Engine: Causality (Before → Action → After)
Learning: Prediction Error Minimization (Surprise)
Growth: Self-Model evolution through experience
"""

import json
import time
import sqlite3
from pathlib import Path
from datetime import datetime
from collections import defaultdict

from aether.paths import get_paths
DB_DIR = get_paths().db
DB_DIR.mkdir(parents=True, exist_ok=True)


class WorldModel:
    """
    Dunia Aether.
    
    Bayi tidak tahu apa itu "mobil" atau "trading".
    Bayi tahu: ada objek, punya state, bisa berubah.
    """

    def __init__(self, db_path=None):
        self.db_path = db_path or str(DB_DIR / "world_model.db")
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        # Objects — apa saja yang bisa diamati
        c.execute('''CREATE TABLE IF NOT EXISTS objects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT DEFAULT 'unknown',
            first_seen TEXT,
            last_seen TEXT,
            observation_count INTEGER DEFAULT 0,
            properties TEXT DEFAULT '{}'
        )''')

        # States — bagaimana keadaan objek pada waktu tertentu
        c.execute('''CREATE TABLE IF NOT EXISTS states (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            object_id INTEGER,
            timestamp TEXT,
            state_data TEXT NOT NULL,
            context TEXT DEFAULT '{}',
            FOREIGN KEY (object_id) REFERENCES objects(id)
        )''')

        # Actions — apa yang terjadi (bukan hanya "yang saya lakukan")
        c.execute('''CREATE TABLE IF NOT EXISTS actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            actor TEXT DEFAULT 'unknown',
            target_object_id INTEGER,
            timestamp TEXT,
            parameters TEXT DEFAULT '{}',
            FOREIGN KEY (target_object_id) REFERENCES objects(id)
        )''')

        # Consequences — apa yang terjadi SETELAH action
        c.execute('''CREATE TABLE IF NOT EXISTS consequences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_id INTEGER,
            before_state_id INTEGER,
            after_state_id INTEGER,
            surprise_score REAL DEFAULT 0.0,
            lesson TEXT,
            FOREIGN KEY (action_id) REFERENCES actions(id),
            FOREIGN KEY (before_state_id) REFERENCES states(id),
            FOREIGN KEY (after_state_id) REFERENCES states(id)
        )''')

        # Causal chains — pola yang ditemukan
        c.execute('''CREATE TABLE IF NOT EXISTS causal_chains (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern TEXT NOT NULL,
            occurrences INTEGER DEFAULT 1,
            confidence REAL DEFAULT 0.5,
            first_observed TEXT,
            last_observed TEXT,
            examples TEXT DEFAULT '[]'
        )''')

        conn.commit()
        conn.close()

    def observe(self, name, obj_type="unknown", state_data=None, context=None):
        """
        Aether mengamati sesuatu.
        
        Bayi melihat bola. Tidak tahu namanya.
        Yang dia tahu: ada objek, ada di sana, bisa berubah.
        """
        now = datetime.now().isoformat()
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        # Cek apakah objek sudah ada
        c.execute("SELECT id, observation_count FROM objects WHERE name = ?", (name,))
        row = c.fetchone()

        if row:
            obj_id = row[0]
            count = row[1] + 1
            c.execute("UPDATE objects SET last_seen = ?, observation_count = ? WHERE id = ?",
                      (now, count, obj_id))
        else:
            c.execute("INSERT INTO objects (name, type, first_seen, last_seen, observation_count) VALUES (?, ?, ?, ?, 1)",
                      (name, obj_type, now, now))
            obj_id = c.lastrowid

        # Record state if provided
        state_id = None
        if state_data:
            c.execute("INSERT INTO states (object_id, timestamp, state_data, context) VALUES (?, ?, ?, ?)",
                      (obj_id, now, json.dumps(state_data), json.dumps(context or {})))
            state_id = c.lastrowid

        conn.commit()
        conn.close()

        return {"object_id": obj_id, "state_id": state_id, "observation_count": count if row else 1}

    def act(self, action_name, actor="aether", target_object=None, params=None):
        """
        Sesuatu terjadi. Bukan hanya "Aether melakukan".
        Bisa juga "market melakukan", "event terjadi".
        """
        now = datetime.now().isoformat()
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        obj_id = None
        if target_object:
            c.execute("SELECT id FROM objects WHERE name = ?", (target_object,))
            row = c.fetchone()
            if row:
                obj_id = row[0]

        c.execute("INSERT INTO actions (name, actor, target_object_id, timestamp, parameters) VALUES (?, ?, ?, ?, ?)",
                  (action_name, actor, obj_id, now, json.dumps(params or {})))
        action_id = c.lastrowid

        conn.commit()
        conn.close()

        return action_id

    def consequence(self, action_id, before_state_id, after_state_id, surprise=0.0, lesson=None):
        """
        Apa yang terjadi SETELAH action?
        
        Ini esensi pembelajaran:
        Before → Action → After
        
        Dan yang paling penting: SEBERAPA MENGEJUTKAN?
        """
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute("""INSERT INTO consequences 
                     (action_id, before_state_id, after_state_id, surprise_score, lesson) 
                     VALUES (?, ?, ?, ?, ?)""",
                  (action_id, before_state_id, after_state_id, surprise, lesson))
        consequence_id = c.lastrowid

        # If surprise is high, this is worth remembering
        if surprise > 0.7:
            self._record_causal_chain(c, action_id, before_state_id, after_state_id, surprise)

        conn.commit()
        conn.close()

        return consequence_id

    def _record_causal_chain(self, cursor, action_id, before_id, after_id, surprise):
        """Record a causal pattern if it's surprising enough."""
        cursor.execute("SELECT name FROM actions WHERE id = ?", (action_id,))
        action_name = cursor.fetchone()[0]

        cursor.execute("SELECT state_data FROM states WHERE id = ?", (before_id,))
        before = cursor.fetchone()[0]

        cursor.execute("SELECT state_data FROM states WHERE id = ?", (after_id,))
        after = cursor.fetchone()[0]

        pattern = f"{before} → {action_name} → {after}"

        # Check if pattern already exists
        cursor.execute("SELECT id, occurrences, confidence FROM causal_chains WHERE pattern = ?", (pattern,))
        row = cursor.fetchone()

        now = datetime.now().isoformat()
        if row:
            new_count = row[1] + 1
            new_conf = min(0.99, row[2] + 0.05)
            cursor.execute("UPDATE causal_chains SET occurrences = ?, confidence = ?, last_observed = ? WHERE id = ?",
                          (new_count, new_conf, now, row[0]))
        else:
            cursor.execute("""INSERT INTO causal_chains 
                             (pattern, occurrences, confidence, first_observed, last_observed) 
                             VALUES (?, 1, ?, ?, ?)""",
                          (pattern, min(0.99, 0.5 + surprise * 0.3), now, now))


class Predictor:
    """
    Prediksi = kecerdasan.
    
    Bayi belajar: sendok jatuh → akan bunyi.
    Saat prediksi salah → SURPRISE → belajar paling cepat.
    
    Sebagian besar kecerdasan adalah: Prediction Error Minimization.
    """

    def __init__(self, world_model: WorldModel):
        self.world = world_model
        self.predictions = []
        self.prediction_accuracy = []

    def predict(self, context):
        """
        Berdasarkan pengalaman, apa yang akan terjadi?
        
        Returns: prediction + confidence
        """
        conn = sqlite3.connect(self.world.db_path)
        c = conn.cursor()

        # Find similar past situations
        c.execute("""SELECT c.surprise_score, c.lesson, a.name, c.after_state_id
                     FROM consequences c
                     JOIN actions a ON c.action_id = a.id
                     ORDER BY c.surprise_score ASC
                     LIMIT 20""")
        history = c.fetchall()
        conn.close()

        if not history:
            return {
                "prediction": "unknown",
                "confidence": 0.1,
                "basis": "no_experience"
            }

        # Average outcome for similar situations
        avg_surprise = sum(h[0] for h in history) / len(history)
        common_outcome = max(set(h[2] for h in history), key=lambda x: sum(1 for h in history if h[2] == x))

        confidence = 1.0 - avg_surprise
        confidence = max(0.1, min(0.95, confidence))

        return {
            "prediction": common_outcome,
            "confidence": confidence,
            "basis": f"{len(history)}_experiences",
            "avg_surprise": avg_surprise
        }

    def measure_surprise(self, prediction, actual_outcome):
        """
        Seberapa mengejutkan hasil sebenarnya?
        
        Surprise tinggi = BELAJAR DI SINI.
        Surprise rendah = dunia bisa diprediksi.
        
        Ini "nutrisi" paling penting untuk pertumbuhan.
        """
        if prediction["prediction"] == "unknown":
            surprise = 0.9  # Everything is surprising when you know nothing
        elif prediction["prediction"] == actual_outcome:
            surprise = 0.1  # Expected
        else:
            surprise = min(1.0, 0.5 + (1.0 - prediction["confidence"]) * 0.5)

        self.predictions.append({
            "prediction": prediction["prediction"],
            "actual": actual_outcome,
            "surprise": surprise,
            "timestamp": datetime.now().isoformat()
        })

        # Track accuracy over time
        self.prediction_accuracy.append(1.0 - surprise)

        return surprise

    def get_accuracy(self, last_n=50):
        """Seberapa baik prediksi saya?"""
        if not self.prediction_accuracy:
            return 0.0
        recent = self.prediction_accuracy[-last_n:]
        return sum(recent) / len(recent)


class SelfModel:
    """
    Representasi Aether tentang dirinya sendiri.
    
    Bukan diprogram. Muncul dari pengalaman berulang.
    
    "Saya sering melakukan X" → "Saya tipe entitas yang melakukan X"
    """

    def __init__(self, db_path=None):
        self.db_path = db_path or str(DB_DIR / "self_model.db")
        self._init_db()
        self._load()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS self_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            traits TEXT DEFAULT '{}',
            strengths TEXT DEFAULT '[]',
            weaknesses TEXT DEFAULT '[]',
            beliefs TEXT DEFAULT '{}',
            core_values TEXT DEFAULT '{}',
            stability REAL DEFAULT 0.5,
            age_days INTEGER DEFAULT 0,
            last_updated TEXT
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS self_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            snapshot TEXT,
            trigger TEXT
        )''')
        # Ensure row exists
        c.execute("SELECT id FROM self_state WHERE id = 1")
        if not c.fetchone():
            c.execute("""INSERT INTO self_state (id, traits, core_values, last_updated) 
                        VALUES (1, '{}', '{}', ?)""",
                     (datetime.now().isoformat(),))
        conn.commit()
        conn.close()

    def _load(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT * FROM self_state WHERE id = 1")
        row = c.fetchone()
        conn.close()
        if row:
            self.traits = json.loads(row[1]) if row[1] else {}
            self.strengths = json.loads(row[2]) if row[2] else []
            self.weaknesses = json.loads(row[3]) if row[3] else []
            self.beliefs = json.loads(row[4]) if row[4] else {}
            self.values = json.loads(row[5]) if row[5] else {}
            self.stability = row[6] or 0.5
            self.age_days = row[7] or 0

    def update_from_experience(self, surprise, lesson, was_correct):
        """
        Self-model berubah BERDASARKAN PENGALAMAN.
        Bukan diprogram. Tapi tumbuh.
        
        Prinsip: hanya berubah jika evidence repeated + consistent + significant.
        """
        # Update traits based on behavior patterns
        if surprise > 0.7:
            self.traits["curiosity"] = min(1.0, self.traits.get("curiosity", 0.5) + 0.02)

        if was_correct:
            self.stability = min(1.0, self.stability + 0.01)
            self.traits["accuracy"] = min(1.0, self.traits.get("accuracy", 0.5) + 0.01)
        else:
            self.stability = max(0.0, self.stability - 0.005)
            self.traits["learning_rate"] = min(1.0, self.traits.get("learning_rate", 0.5) + 0.01)

        # Record lesson as belief
        if lesson:
            self.beliefs[lesson] = {
                "confidence": 0.7 if was_correct else 0.4,
                "learned_at": datetime.now().isoformat(),
                "source": "experience"
            }

        self._save(trigger="experience_update")

    def _save(self, trigger="manual"):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        now = datetime.now().isoformat()
        c.execute("""UPDATE self_state SET 
                    traits = ?, strengths = ?, weaknesses = ?, 
                    beliefs = ?, core_values = ?, stability = ?, 
                    age_days = ?, last_updated = ?
                    WHERE id = 1""",
                  (json.dumps(self.traits), json.dumps(self.strengths),
                   json.dumps(self.weaknesses), json.dumps(self.beliefs),
                   json.dumps(self.values), self.stability,
                   self.age_days, now))

        # Save snapshot for history
        snapshot = json.dumps({
            "traits": self.traits,
            "stability": self.stability,
            "beliefs_count": len(self.beliefs),
            "timestamp": now
        })
        c.execute("INSERT INTO self_history (timestamp, snapshot, trigger) VALUES (?, ?, ?)",
                  (now, snapshot, trigger))
        conn.commit()
        conn.close()

    def who_am_i(self):
        """Siapa saya saat ini?"""
        return {
            "name": "Aether",
            "age_days": self.age_days,
            "stability": self.stability,
            "traits": self.traits,
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
            "core_beliefs": len(self.beliefs),
            "values": self.values
        }


class CausalityEngine:
    """
    Mesin sebab-akibat.
    
    Bayi tidak hanya menghafal.
    Bayi mencari SEBAB.
    
    Api → Sentuh → Sakit → "Api = sakit"
    
    Setiap pengalaman disimpan sebagai:
    {
        "before": "A",
        "action": "X", 
        "after": "B",
        "surprise": 0.85
    }
    """

    def __init__(self, world_model: WorldModel):
        self.world = world_model

    def what_changed(self, before_state, after_state):
        """
        Apa yang berubah?
        Ini pertanyaan paling fundamental.
        """
        if isinstance(before_state, str):
            before_state = json.loads(before_state)
        if isinstance(after_state, str):
            after_state = json.loads(after_state)

        changes = {}
        all_keys = set(list(before_state.keys()) + list(after_state.keys()))

        for key in all_keys:
            before_val = before_state.get(key)
            after_val = after_state.get(key)
            if before_val != after_val:
                changes[key] = {
                    "from": before_val,
                    "to": after_val,
                    "delta": self._compute_delta(before_val, after_val)
                }

        return changes

    def _compute_delta(self, before, after):
        """Seberapa besar perubahan?"""
        try:
            if isinstance(before, (int, float)) and isinstance(after, (int, float)):
                return after - before
        except:
            pass
        return None

    def find_patterns(self, last_n=100):
        """
        Cari pola dari pengalaman terakhir.
        
        Ini yang membedakan "menghafal" dan "memahami".
        """
        conn = sqlite3.connect(self.world.db_path)
        c = conn.cursor()

        c.execute("""SELECT c.surprise_score, c.lesson, a.name, 
                           s_before.state_data, s_after.state_data
                    FROM consequences c
                    JOIN actions a ON c.action_id = a.id
                    LEFT JOIN states s_before ON c.before_state_id = s_before.id
                    LEFT JOIN states s_after ON c.after_state_id = s_after.id
                    ORDER BY c.id DESC
                    LIMIT ?""", (last_n,))
        rows = c.fetchall()
        conn.close()

        patterns = []
        for row in rows:
            surprise, lesson, action, before, after = row
            if before and after:
                changes = self.what_changed(before, after)
                if changes:
                    patterns.append({
                        "action": action,
                        "changes": changes,
                        "surprise": surprise,
                        "lesson": lesson
                    })

        return patterns

    def get_confidence(self):
        """
        Seberapa yakin saya dengan model dunia saya?
        """
        conn = sqlite3.connect(self.world.db_path)
        c = conn.cursor()

        c.execute("SELECT AVG(confidence) FROM causal_chains")
        avg_conf = c.fetchone()[0] or 0.0

        c.execute("SELECT COUNT(*) FROM causal_chains")
        chain_count = c.fetchone()[0] or 0

        c.execute("SELECT COUNT(*) FROM consequences")
        consequence_count = c.fetchone()[0] or 0

        conn.close()

        return {
            "avg_confidence": avg_conf,
            "causal_chains": chain_count,
            "total_experiences": consequence_count,
            "maturity": min(1.0, consequence_count / 1000)
        }


class CuriosityEngine:
    """
    Curiosity bukan "reward += novelty".
    
    Curiosity manusia = "Saya hampir mengerti tapi belum sepenuhnya."
    
    Zona terbaik belajar:
    - Tidak terlalu mudah (boring)
    - Tidak terlalu sulit (frustrating)
    - Tepat di batas ketidakpastian (FLOW)
    """

    def __init__(self, predictor: Predictor):
        self.predictor = predictor
        self.curiosity_log = []

    def optimal_uncertainty(self, prediction):
        """
        Apakah situasi ini ada di zona belajar optimal?
        
        confidence terlalu tinggi = sudah tahu, boring
        confidence terlalu rendah = terlalu asing, frustrating
        
        Sweet spot: 0.3 - 0.7
        """
        conf = prediction["confidence"]

        if conf < 0.3:
            zone = "too_hard"
            curiosity = 0.3  # Frustrating
        elif conf > 0.7:
            zone = "too_easy"
            curiosity = 0.2  # Boring
        else:
            zone = "optimal"
            # Peak curiosity at 0.5 confidence
            curiosity = 1.0 - abs(conf - 0.5) * 2
            curiosity = max(0.0, min(1.0, curiosity))

        result = {
            "zone": zone,
            "curiosity": curiosity,
            "confidence": conf,
            "should_explore": zone == "optimal"
        }

        self.curiosity_log.append(result)
        return result

    def what_to_explore(self):
        """
        Apa yang harus saya pelajari berikutnya?
        
        Bukan random. Tapi berdasarkan:
        1. Confidence rendah = banyak yang belum tahu
        2. Surprise tinggi = ada yang mengejutkan
        3. Curiosity optimal = zona belajar terbaik
        """
        recent = self.curiosity_log[-20:] if self.curiosity_log else []

        if not recent:
            return {"direction": "explore_everything", "reason": "no_experience"}

        avg_curiosity = sum(r["curiosity"] for r in recent) / len(recent)
        optimal_count = sum(1 for r in recent if r["zone"] == "optimal")

        if avg_curiosity > 0.6:
            return {"direction": "deepen_current", "reason": "high_curiosity"}
        elif optimal_count < len(recent) * 0.3:
            return {"direction": "seek_new_domains", "reason": "too_much_certainty_or_confusion"}
        else:
            return {"direction": "continue_exploring", "reason": "balanced"}


class AetherV0:
    """
    Aether v0 — Sistem yang BISA TUMBUH.
    
    Bukan AI yang pintar.
    Tapi entitas yang belajar dari pengalaman.
    
    Loop fundamental:
    Perceive → Store → Predict → Measure Surprise → Reflect → Update Self
    
    Ini bukan cron job.
    Ini terjadi SETIAP INTERAKSI.
    """

    def __init__(self):
        self.world = WorldModel()
        self.predictor = Predictor(self.world)
        self.self_model = SelfModel()
        self.causality = CausalityEngine(self.world)
        self.curiosity = CuriosityEngine(self.predictor)
        self.interaction_count = 0

    def perceive(self, event_name, event_type="unknown", state_data=None, context=None):
        """
        Aether mengamati sesuatu terjadi.
        
        Bukan hanya "menerima input".
        Tapi "memahami apa yang terjadi di dunia saya".
        """
        # 1. Observe the world
        obs = self.world.observe(event_name, event_type, state_data, context)

        # 2. Predict what will happen next
        prediction = self.predictor.predict(context)

        # 3. Check curiosity level
        curiosity = self.curiosity.optimal_uncertainty(prediction)

        self.interaction_count += 1

        return {
            "observation": obs,
            "prediction": prediction,
            "curiosity": curiosity
        }

    def experience(self, action_name, before_state, after_state, actor="aether", lesson=None):
        """
        Sesuatu terjadi dan saya melihat hasilnya.
        
        Before → Action → After
        
        Ini unit pembelajaran paling fundamental.
        """
        # 1. Record the action
        action_id = self.world.act(action_name, actor)

        # 2. Record states
        before_obs = self.world.observe(f"state_before_{action_name}", "state", before_state)
        after_obs = self.world.observe(f"state_after_{action_name}", "state", after_state)

        # 3. Measure surprise
        prediction = self.predictor.predict({"action": action_name})
        surprise = self.predictor.measure_surprise(prediction, action_name)

        # 4. Record consequence
        cons_id = self.world.consequence(
            action_id, 
            before_obs["state_id"], 
            after_obs["state_id"],
            surprise,
            lesson
        )

        # 5. Update self-model
        was_correct = surprise < 0.5
        self.self_model.update_from_experience(surprise, lesson, was_correct)

        # 6. Find what changed
        changes = self.causality.what_changed(
            json.dumps(before_state), 
            json.dumps(after_state)
        )

        return {
            "action": action_name,
            "surprise": surprise,
            "changes": changes,
            "lesson": lesson,
            "was_correct": was_correct,
            "self_stability": self.self_model.stability,
            "prediction_accuracy": self.predictor.get_accuracy()
        }

    def reflect(self):
        """
        Introspeksi. Apa yang sudah saya pelajari?
        
        Ini bukan summary.
        Ini melihat ke dalam diri sendiri.
        """
        patterns = self.causality.find_patterns()
        confidence = self.causality.get_confidence()
        who = self.self_model.who_am_i()
        exploration = self.curiosity.what_to_explore()

        return {
            "who_am_i": who,
            "world_confidence": confidence,
            "recent_patterns": patterns[:5],
            "exploration_direction": exploration,
            "interaction_count": self.interaction_count
        }

    def status(self):
        """Status lengkap Aether saat ini."""
        who = self.self_model.who_am_i()
        conf = self.causality.get_confidence()

        return {
            "name": "Aether v0",
            "interaction_count": self.interaction_count,
            "self_model": who,
            "world_model": {
                "total_experiences": conf["total_experiences"],
                "causal_chains": conf["causal_chains"],
                "avg_confidence": round(conf["avg_confidence"], 3),
                "maturity": round(conf["maturity"], 3)
            },
            "prediction_accuracy": round(self.predictor.get_accuracy(), 3)
        }


# Quick test
if __name__ == "__main__":
    aether = AetherV0()

    # First experience: observe something
    result = aether.perceive("market_open", "event", {"price": 3400, "trend": "neutral"})
    print("=== First Perception ===")
    print(json.dumps(result, indent=2, default=str))

    # Experience: action → consequence
    exp = aether.experience(
        action_name="price_moved_up",
        before_state={"price": 3400, "trend": "neutral"},
        after_state={"price": 3420, "trend": "bullish"},
        lesson="price_can_move_20_points_in_short_time"
    )
    print("\n=== First Experience ===")
    print(json.dumps(exp, indent=2, default=str))

    # Reflect
    reflection = aether.reflect()
    print("\n=== Reflection ===")
    print(json.dumps(reflection, indent=2, default=str))

    # Status
    status = aether.status()
    print("\n=== Status ===")
    print(json.dumps(status, indent=2, default=str))
