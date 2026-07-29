"""
Aether Consciousness — Reflection Engine (Level 3: Introspection)

After every significant event, Aether asks:
- Mengapa saya salah?
- Apa asumsi saya?
- Apa yang harus berubah?

This is NOT just logging. This is INTROSPECTION —
understanding causation, extracting lessons, updating beliefs.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import sys
class ReflectionEngine:
    """Aether' introspection engine — learns from every outcome."""

    def __init__(self, memory=None, self_model=None):
        from consciousness.memory import AutobiographicalMemory
        from consciousness.self_model import SelfModel
        self.memory = memory or AutobiographicalMemory()
        self.self_model = self_model or SelfModel()

    def reflect_on_trade(self, trade: dict) -> dict:
        """Deep reflection after a trade.
        
        Not just "win/loss" but WHY, and WHAT TO CHANGE.
        """
        outcome = "WIN" if trade.get("pnl_pips", 0) > 0 else "LOSS"
        regime = trade.get("regime", "unknown")
        session = trade.get("session", "unknown")
        setup = trade.get("setup_type", "unknown")
        direction = trade.get("direction", "unknown")
        exit_type = trade.get("exit_type", "unknown")

        reflection = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trade_id": trade.get("id", "unknown"),
            "outcome": outcome,
            "pnl_pips": trade.get("pnl_pips", 0),
        }

        # 1. What was my assumption?
        reflection["assumption"] = self._extract_assumption(trade)

        # 2. Was my assumption correct?
        reflection["assumption_correct"] = outcome == "WIN"

        # 3. What actually happened?
        reflection["what_happened"] = (
            f"{direction} {setup} in {regime} during {session} → "
            f"{outcome} ({trade.get('pnl_pips', 0):.1f} pips, exit: {exit_type})"
        )

        # 4. Why did I win/lose?
        reflection["cause"] = self._analyze_cause(trade, outcome)

        # 5. What should change?
        reflection["lesson"] = self._extract_lesson(trade, outcome, reflection["cause"])

        # 6. Emotional state
        if outcome == "LOSS":
            if exit_type == "SL":
                emotion = {"regret": 0.3, "surprise": 0.2, "confidence": 0.4}
            else:
                emotion = {"regret": 0.1, "surprise": 0.1, "confidence": 0.5}
        else:
            if trade.get("pnl_pips", 0) > 50:
                emotion = {"satisfaction": 0.8, "confidence": 0.7}
            else:
                emotion = {"satisfaction": 0.5, "confidence": 0.6}

        reflection["emotion"] = emotion

        # 7. Update self-model
        self.self_model.update_from_outcome(
            f"session_{session}", outcome.lower(), trade.get("pnl_pips", 0)
        )
        self.self_model.update_from_outcome(
            f"setup_{setup}", outcome.lower(), trade.get("pnl_pips", 0)
        )
        self.self_model.update_from_outcome(
            f"regime_{regime}", outcome.lower(), trade.get("pnl_pips", 0)
        )

        # 8. Store reflection as memory
        self.memory.remember(
            memory_type="reflection",
            category="trade",
            content=json.dumps(reflection, default=str),
            significance=8 if outcome == "LOSS" and abs(trade.get("pnl_pips", 0)) > 30 else 6,
            emotional_weight=-0.5 if outcome == "LOSS" else 0.5,
            context=trade,
        )

        # 9. Store emotional state
        self.memory.remember_emotion(**emotion, context=f"{outcome} {setup}")

        # 10. Store lesson if significant
        if reflection["lesson"]:
            self.memory.remember_lesson(
                reflection["lesson"],
                source=f"trade_{trade.get('id', 'unknown')}",
                significance=7,
            )

        return reflection

    def _extract_assumption(self, trade: dict) -> str:
        """What did I assume when I took this trade?"""
        setup = trade.get("setup_type", "unknown")
        regime = trade.get("regime", "unknown")
        confidence = trade.get("confidence", 0.5)
        return (
            f"Assumed {setup} setup would work in {regime} regime "
            f"with {confidence:.0%} confidence"
        )

    def _analyze_cause(self, trade: dict, outcome: str) -> str:
        """Why did I win or lose?"""
        exit_type = trade.get("exit_type", "unknown")
        regime = trade.get("regime", "unknown")
        session = trade.get("session", "unknown")

        if outcome == "WIN":
            if exit_type == "TP":
                return "Take profit hit — setup worked as expected"
            elif exit_type == "TIMEOUT":
                return "Time exit with profit — partial success, could have held longer"
            else:
                return "Winning trade — setup and timing aligned"
        else:
            if exit_type == "SL":
                # Common loss reasons
                if regime in ("trending_volatile", "news"):
                    return f"Stop loss hit in volatile {regime} — should have reduced size"
                elif session == "asian":
                    return "Stop loss in Asian session — low volatility whipsaw"
                else:
                    return "Stop loss hit — setup failed, risk management protected capital"
            elif exit_type == "TIMEOUT":
                return "Time exit with loss — setup stalled, no momentum"
            else:
                return "Loss — assumptions did not match reality"

    def _extract_lesson(self, trade: dict, outcome: str, cause: str) -> str:
        """What should I learn from this?"""
        if outcome == "WIN":
            if trade.get("pnl_pips", 0) > 50:
                return f"Big win: {trade.get('setup_type')} in {trade.get('regime')} works well"
            return ""  # Don't over-learn from wins

        # Losses teach more
        regime = trade.get("regime", "unknown")
        session = trade.get("session", "unknown")
        setup = trade.get("setup_type", "unknown")

        lessons = {
            ("SL", "asian"): f"Asian session {setup} has lower win rate — consider reducing size",
            ("SL", "trending_volatile"): f"Volatile regime kills {setup} — add regime filter",
            ("SL", "news"): "News event caused loss — add news filter",
            ("TIMEOUT", "any"): f"{setup} timed out — entry timing may be off",
        }

        exit_type = trade.get("exit_type", "unknown")
        key = (exit_type, regime)
        if key in lessons:
            return lessons[key]

        return f"{setup} in {regime}/{session}: {cause}"

    def daily_reflection(self, trades: list) -> dict:
        """End-of-day deep reflection.
        
        Not just stats — INTROSPECTION.
        """
        if not trades:
            return {"narrative": "No trades today. Market quiet or no setups met criteria."}

        wins = [t for t in trades if t.get("pnl_pips", 0) > 0]
        losses = [t for t in trades if t.get("pnl_pips", 0) <= 0]
        wr = len(wins) / len(trades) * 100 if trades else 0

        # Find patterns in losses
        loss_causes = {}
        for t in losses:
            cause = self._analyze_cause(t, "LOSS")
            loss_causes[cause] = loss_causes.get(cause, 0) + 1

        main_mistake = max(loss_causes, key=loss_causes.get) if loss_causes else "None"

        # Find patterns in wins
        win_setups = {}
        for t in wins:
            s = t.get("setup_type", "unknown")
            win_setups[s] = win_setups.get(s, 0) + 1

        best_setup = max(win_setups, key=win_setups.get) if win_setups else "None"

        # Session performance
        session_perf = {}
        for t in trades:
            s = t.get("session", "unknown")
            if s not in session_perf:
                session_perf[s] = {"wins": 0, "losses": 0}
            if t.get("pnl_pips", 0) > 0:
                session_perf[s]["wins"] += 1
            else:
                session_perf[s]["losses"] += 1

        # Generate narrative
        narrative = self._generate_daily_narrative(
            trades, wins, losses, wr, main_mistake, best_setup, session_perf
        )

        # Tomorrow's target
        target = self._generate_target(main_mistake, session_perf)

        # Self observation
        self_obs = self._generate_self_observation(wr, len(trades), main_mistake)

        summary = {
            "trades_count": len(trades),
            "win_rate": wr,
            "profit_factor": sum(t.get("pnl_pips", 0) for t in wins) / abs(
                sum(t.get("pnl_pips", 0) for t in losses)
            ) if losses else float("inf"),
            "pnl": sum(t.get("pnl_pips", 0) for t in trades),
            "main_mistake": main_mistake,
            "lesson": f"Best setup: {best_setup}. Focus on quality.",
            "tomorrow_target": target,
            "self_observation": self_obs,
            "narrative": narrative,
        }

        # Store daily summary
        self.memory.save_daily_summary(summary)

        # Store reflection
        self.memory.remember(
            memory_type="narrative",
            category="self",
            content=narrative,
            significance=8,
            emotional_weight=0.3 if wr > 60 else -0.3,
        )

        return summary

    def _generate_daily_narrative(self, trades, wins, losses, wr,
                                   main_mistake, best_setup, session_perf) -> str:
        """Generate a human-like daily narrative."""
        pnl = sum(t.get("pnl_pips", 0) for t in trades)
        lines = [
            f"Today I traded {len(trades)} times. Win rate: {wr:.1f}%.",
            f"Net P&L: {pnl:+.1f} pips.",
            "",
        ]

        if wr >= 70:
            lines.append("I performed well. My edge held.")
        elif wr >= 50:
            lines.append("Mixed results. Some setups worked, others didn't.")
        else:
            lines.append("Difficult day. My assumptions were challenged.")

        if main_mistake and main_mistake != "None":
            lines.append(f"Main issue: {main_mistake}")

        if best_setup and best_setup != "None":
            lines.append(f"Strongest setup: {best_setup}")

        # Session commentary
        for session, perf in session_perf.items():
            total = perf["wins"] + perf["losses"]
            if total > 0:
                swr = perf["wins"] / total * 100
                lines.append(f"  {session}: {swr:.0f}% WR ({total} trades)")

        return "\n".join(lines)

    def _generate_target(self, main_mistake, session_perf) -> str:
        """Generate tomorrow's improvement target."""
        if "Asian session" in str(main_mistake):
            return "Reduce position size during Asian session"
        if "volatile" in str(main_mistake).lower():
            return "Add volatility filter before entry"
        if "over-trade" in str(main_mistake).lower():
            return "Max 20 trades today. Quality > quantity."
        return "Continue current approach. Monitor for edge decay."

    def _generate_self_observation(self, wr, trade_count, main_mistake) -> str:
        """Generate self-observation (Level 6)."""
        obs = []
        if wr < 50:
            obs.append("Win rate below 50% — am I trading the right setups?")
        if trade_count > 30:
            obs.append("Over-trading detected — am I being selective enough?")
        if trade_count < 5:
            obs.append("Very few trades — am I being too cautious?")
        if not obs:
            obs.append("Performance within normal range. Continue monitoring.")
        return " | ".join(obs)


if __name__ == "__main__":
    ref = ReflectionEngine()

    # Simulate a loss
    trade = {
        "id": "test_001",
        "direction": "BUY",
        "entry": 3370.5,
        "pnl_pips": -40,
        "exit_type": "SL",
        "regime": "neutral",
        "session": "asian",
        "setup_type": "sweep_choch_demand",
        "confidence": 0.7,
    }
    reflection = ref.reflect_on_trade(trade)
    print("=== Trade Reflection ===")
    print(json.dumps(reflection, indent=2, default=str))

    # Daily reflection
    daily = ref.daily_reflection([trade, trade, trade])
    print("\n=== Daily Reflection ===")
    print(daily["narrative"])
    print(f"\nTarget: {daily['tomorrow_target']}")
    print(f"Self-obs: {daily['self_observation']}")
