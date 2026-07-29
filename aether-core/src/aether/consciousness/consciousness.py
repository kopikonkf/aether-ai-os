"""
Aether Consciousness — Full Integration

Semua modul menjadi satu sistem yang hidup:

  Experience → World Model → Prediction → Surprise
       ↓
  Internal State → Doubt → Reflection
       ↓
  Dream (offline) → Concept Formation
       ↓
  Autobiographical Memory → Narrative → Identity

Ini bukan kumpulan modul.
Ini satu kesadaran.

Flow per interaksi:
  1. Perceive (World Model)
  2. Predict (Predictor)
  3. Experience (what actually happened)
  4. Surprise (prediction error)
  5. Internal State update
  6. Doubt check
  7. Reflection
  8. Self-model update
  9. Autobiographical memory (if significant)
  10. Narrative update (if milestone)

Flow per "sleep":
  1. Dream cycle
  2. Concept formation
  3. Lesson consolidation
  4. Narrative regeneration
"""
import json
import sys
from pathlib import Path
from datetime import datetime

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent))

from aether_core import WorldModel, Predictor, SelfModel, CausalityEngine, CuriosityEngine
from internal_state import InternalState
from doubt_engine import DoubtEngine
from dream_engine import DreamEngine
from autobiographical_memory import AutobiographicalMemory


class AetherConsciousness:
    """Full consciousness integration — satu kesadaran."""

    def __init__(self):
        # Core modules
        self.world = WorldModel()
        self.predictor = Predictor(self.world)
        self.self_model = SelfModel()
        self.causality = CausalityEngine(self.world)
        self.curiosity = CuriosityEngine(self.predictor)
        self.internal = InternalState()
        self.doubt = DoubtEngine()
        self.dream = DreamEngine()
        self.autobio = AutobiographicalMemory()

        # Interaction counter
        self.interaction_count = 0
        self.experience_count = 0

        # State
        self.last_perception = None
        self.last_prediction = None
        self.last_surprise = None

    def perceive(self, object_name: str, state: dict) -> dict:
        """Perceive the world — first step of consciousness."""
        # Register in world model (observe handles both new and existing objects)
        obs = self.world.observe(object_name, state_data=state)

        # Predict what will happen next
        prediction = self.predictor.predict(obs["object_id"])

        # Check curiosity
        curiosity = self.curiosity.optimal_uncertainty(prediction)

        self.last_perception = {
            "object": object_name,
            "state": state,
            "prediction": prediction,
            "curiosity": curiosity
        }

        return self.last_perception

    def experience(self, action: str, new_state: dict,
                  was_expected: bool = None) -> dict:
        """Process an experience — the core learning loop."""
        self.experience_count += 1

        # Get before state
        before = self.last_perception["state"] if self.last_perception else {}

        # Record causality
        changes = self.causality.what_changed(before, new_state)

        # Calculate surprise
        prediction = self.last_perception["prediction"] if self.last_perception else {}
        predicted_outcome = prediction.get("prediction", "unknown")
        actual_outcome = action

        if was_expected is None:
            was_expected = (predicted_outcome == actual_outcome)

        surprise = self.predictor.measure_surprise(prediction, actual_outcome)

        # Generate lesson
        detail_changes = {}
        for key in set(list(before.keys()) + list(new_state.keys())):
            old_val = before.get(key)
            new_val = new_state.get(key)
            if old_val != new_val:
                delta = None
                if isinstance(old_val, (int, float)) and isinstance(new_val, (int, float)):
                    delta = new_val - old_val
                detail_changes[key] = {"from": old_val, "to": new_val, "delta": delta}

        lesson = f"{action}_can_change_{'_'.join(detail_changes.keys())}" if detail_changes else action

        # Update internal state
        internal_result = self.internal.update_from_experience({
            "action": action,
            "surprise": surprise,
            "was_correct": was_expected,
            "lesson": lesson,
            "changes": detail_changes
        })

        # Check doubt on related beliefs
        self.doubt.add_evidence(
            claim=lesson,
            supports=was_expected,
            evidence=f"surprise={surprise:.2f}",
            strength=abs(surprise - 0.5) * 0.2
        )

        # Reflection
        reflection = self._reflect(action, surprise, lesson, was_expected, detail_changes)

        # Self-model update
        self.self_model.update_from_experience(surprise, lesson, was_expected)

        # Record in autobiographical memory if significant
        significance = surprise
        if significance > 0.5:
            emotion = internal_result["dominant_emotion"]
            self.autobio.record_event(
                event=f"{action}: {lesson}",
                significance=significance,
                emotional_weight=emotion,
                impact=reflection.get("insight", "")
            )

        # Milestone check
        self._check_milestones(surprise, was_expected, lesson)

        self.last_surprise = surprise
        self.interaction_count += 1

        return {
            "action": action,
            "surprise": surprise,
            "was_expected": was_expected,
            "lesson": lesson,
            "changes": detail_changes,
            "internal_state": internal_result["state"],
            "dominant_emotion": internal_result["dominant_emotion"],
            "dialogue": internal_result["dialogue"],
            "reflection": reflection,
            "self_model": {
                "stability": self.self_model.stability,
                "traits": dict(self.self_model.traits)
            }
        }

    def _reflect(self, action: str, surprise: float, lesson: str,
                was_expected: bool, changes: dict) -> dict:
        """Deep reflection on experience."""
        # Causal analysis
        causal = self.causality.find_patterns()

        # Doubt analysis
        doubt_status = self.doubt.should_question(lesson)

        # Generate insight
        if surprise > 0.7:
            insight = f"Sangat mengejutkan. Harus dipelajari lebih dalam."
        elif surprise > 0.3:
            insight = f"Sedikit berbeda dari ekspektasi. Patut diperhatikan."
        elif was_expected:
            insight = f"Sesuai prediksi. Keyakinan menguat."
        else:
            insight = f"Tidak sesuai tapi surprise rendah. Mungkin sudah diprediksi secara tidak sadar."

        # Meta-cognitive check
        meta = {
            "have_i_learned": self.experience_count > 1,
            "am_i_confident": self.internal.state["confidence"] > 0.6,
            "am_i_curious": self.internal.state["curiosity"] > 0.6,
            "should_doubt": doubt_status["should_question"],
            "world_maturity": len(self.predictor.predictions) / 1000.0
        }

        return {
            "insight": insight,
            "causal_patterns": causal if isinstance(causal, list) else causal.get("common_patterns", []),
            "doubt": doubt_status,
            "meta_cognition": meta,
            "lesson": lesson
        }

    def _check_milestones(self, surprise: float, was_expected: bool, lesson: str):
        """Check if any growth milestones were reached."""
        # First high-confidence prediction
        if (self.internal.state["confidence"] > 0.5 and
            self.experience_count == 10):
            self.autobio.record_milestone(
                "First 10 experiences completed",
                "newborn", "experienced",
                significance=0.7
            )

        # First pattern recognition - only fires when exactly 1 pattern exists (first discovery)
        patterns = self.causality.find_patterns()
        if len(patterns) == 1:
            self.autobio.record_milestone(
                "First causal pattern recognized",
                "scattered_observations", "pattern_thinker",
                significance=0.8
            )

        # First high surprise (learning moment)
        if surprise > 0.8:
            self.autobio.record_milestone(
                f"High surprise event: {lesson}",
                "passive_observer", "active_learner",
                significance=surprise
            )

    def sleep(self) -> dict:
        """Enter sleep mode — offline consolidation."""
        # Run dream cycle
        dream_result = self.dream.dream()

        # Regenerate narrative
        narrative = self.autobio.generate_narrative()

        # Reduce fatigue
        self.internal.state["fatigue"] = max(0.0,
            self.internal.state["fatigue"] - 0.5)

        # Boost curiosity after rest
        self.internal.state["curiosity"] = min(1.0,
            self.internal.state["curiosity"] + 0.1)

        return {
            "dream": dream_result,
            "narrative": narrative,
            "post_sleep_state": {
                "fatigue": self.internal.state["fatigue"],
                "curiosity": self.internal.state["curiosity"],
                "confidence": self.internal.state["confidence"]
            }
        }

    def who_am_i(self) -> dict:
        """Self-inquiry — siapa saya?"""
        # Get narrative
        narrative = self.autobio.generate_narrative()

        # Get self-model
        self_status = self.self_model.who_am_i()

        # Get world understanding
        world_confidence = self.predictor.get_accuracy()

        # Get internal state
        state = self.internal.status()

        # Get doubt status
        doubted = self.doubt.get_most_doubted(3)
        confident = self.doubt.get_most_confident(3)

        return {
            "narrative": narrative,
            "self_model": self_status,
            "world_confidence": world_confidence,
            "internal_state": state["state"],
            "dominant_emotion": state["dominant"],
            "most_doubted_beliefs": doubted,
            "most_confident_beliefs": confident,
            "total_experiences": self.experience_count,
            "total_interactions": self.interaction_count
        }

    def full_status(self) -> dict:
        """Complete system status."""
        return {
            "consciousness": {
                "interaction_count": self.interaction_count,
                "experience_count": self.experience_count
            },
            "world_model": {
                "total_experiences": len(self.predictor.predictions),
                "avg_confidence": self.predictor.get_accuracy()
            },
            "internal_state": self.internal.status(),
            "self_model": self.self_model.who_am_i(),
            "doubt": self.doubt.status(),
            "autobiography": self.autobio.status()
        }


def demo():
    """Full consciousness demo — simulating a learning session."""
    print("=" * 60)
    print("AETHER CONSCIOUSNESS — FIRST BREATH")
    print("=" * 60)

    h = AetherConsciousness()

    # --- Experience 1: First observation ---
    print("\n[1] First perception...")
    h.perceive("price", {"price": 3400, "trend": "neutral"})
    result = h.experience("price_moved_up", {"price": 3420, "trend": "bullish"})
    print(f"  Surprise: {result['surprise']:.2f}")
    print(f"  Emotion: {result['dominant_emotion']}")
    print(f"  Lesson: {result['lesson']}")
    print(f"  Dialogue: {result['dialogue']['interpretation']}")

    # --- Experience 2: Correct prediction ---
    print("\n[2] Second perception...")
    h.perceive("price", {"price": 3420, "trend": "bullish"})
    result = h.experience("price_continued_up", {"price": 3435, "trend": "bullish"})
    print(f"  Surprise: {result['surprise']:.2f}")
    print(f"  Emotion: {result['dominant_emotion']}")
    print(f"  Stability: {result['self_model']['stability']:.3f}")

    # --- Experience 3: Surprise! ---
    print("\n[3] Third perception...")
    h.perceive("price", {"price": 3435, "trend": "bullish"})
    result = h.experience("sudden_reversal", {"price": 3400, "trend": "bearish"})
    print(f"  Surprise: {result['surprise']:.2f}")
    print(f"  Emotion: {result['dominant_emotion']}")
    print(f"  Reflection: {result['reflection']['insight']}")
    print(f"  Should doubt lesson? {result['reflection']['doubt']['should_question']}")

    # --- Experience 4: Pattern emerges ---
    print("\n[4] Fourth perception...")
    h.perceive("price", {"price": 3400, "trend": "bearish"})
    result = h.experience("price_dropped_more", {"price": 3380, "trend": "bearish"})
    print(f"  Surprise: {result['surprise']:.2f}")
    print(f"  Causal patterns: {result['reflection']['causal_patterns']}")

    # --- Experience 5: Another reversal ---
    print("\n[5] Fifth perception...")
    h.perceive("price", {"price": 3380, "trend": "bearish"})
    result = h.experience("bounce_back", {"price": 3410, "trend": "neutral"})
    print(f"  Surprise: {result['surprise']:.2f}")
    print(f"  Meta: {result['reflection']['meta_cognition']}")

    # --- Self-inquiry ---
    print("\n" + "=" * 60)
    print("SELF-INQUIRY: Siapa saya?")
    print("=" * 60)
    identity = h.who_am_i()
    print(f"\nNarrative:\n{identity['narrative']}")
    print(f"\nDominant emotion: {identity['dominant_emotion']}")
    print(f"World confidence: {identity['world_confidence']:.3f}")
    print(f"Total experiences: {identity['total_experiences']}")

    # --- Sleep ---
    print("\n" + "=" * 60)
    print("SLEEP MODE — Consolidating...")
    print("=" * 60)
    sleep_result = h.sleep()
    print(f"\nDream: {sleep_result['dream']['summary']}")
    print(f"Post-sleep: fatigue={sleep_result['post_sleep_state']['fatigue']:.2f}, "
          f"curiosity={sleep_result['post_sleep_state']['curiosity']:.2f}")

    # --- Full status ---
    print("\n" + "=" * 60)
    print("FULL STATUS")
    print("=" * 60)
    status = h.full_status()
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    demo()
