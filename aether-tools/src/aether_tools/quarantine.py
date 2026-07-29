"""
Behavioral monitoring and automatic quarantine system for Aether agent.
Tracks metrics, detects anomalies, and enforces security profile downgrades.
"""

import time
import json
import logging
import math
from pathlib import Path
from collections import deque
from dataclasses import dataclass, field
from typing import Literal, Optional

log = logging.getLogger(__name__)


@dataclass
class MetricWindow:
    """Sliding time window for metric tracking"""
    window_seconds: int
    events: deque = field(default_factory=deque)
    
    def add(self, timestamp: float = None):
        if timestamp is None:
            timestamp = time.time()
        self.events.append(timestamp)
        self._cleanup()
    
    def _cleanup(self):
        cutoff = time.time() - self.window_seconds
        while self.events and self.events[0] < cutoff:
            self.events.popleft()
    
    def count(self) -> int:
        self._cleanup()
        return len(self.events)


@dataclass
class QuarantineState:
    """Current quarantine state"""
    in_quarantine: bool = False
    quarantine_start: Optional[float] = None
    quarantine_reason: Optional[str] = None
    original_profile: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "in_quarantine": self.in_quarantine,
            "quarantine_start": self.quarantine_start,
            "quarantine_reason": self.quarantine_reason,
            "original_profile": self.original_profile
        }
    
    @classmethod
    def from_dict(cls, data: dict):
        return cls(**data)


class BehaviorMonitor:
    """
    Monitors agent behavior and enforces quarantine based on configured thresholds.
    """
    
    def __init__(self, config_path: Path, state_path: Path):
        self.config_path = config_path
        self.state_path = state_path
        self.config = self._load_config()
        self.state = self._load_state()
        
        # Initialize metric windows
        q = self.config.get("quarantine", {})
        self.error_window = MetricWindow(q.get("error_threshold", {}).get("window_minutes", 15) * 60)
        self.tool_window = MetricWindow(q.get("tool_spam_threshold", {}).get("window_minutes", 5) * 60)
        self.write_window = MetricWindow(q.get("write_threshold", {}).get("window_minutes", 10) * 60)
        self.api_window = MetricWindow(q.get("api_threshold", {}).get("window_minutes", 60) * 60)
        
        # Trust score tracking. The profile observation clock must survive
        # Gateway restarts; otherwise trust graduation can never accumulate.
        self.trust_score = self._load_trust_score()
        self.profile_start_time = self._load_profile_start_time()
        self._ensure_profile_start_time_persisted()
    
    def _load_config(self) -> dict:
        """Load security profiles config"""
        try:
            import yaml
            with open(self.config_path) as f:
                return yaml.safe_load(f)
        except Exception as e:
            log.error(f"Failed to load quarantine config: {e}")
            return {}
    
    def _load_state(self) -> QuarantineState:
        """Load quarantine state from disk"""
        try:
            if self.state_path.exists():
                with open(self.state_path) as f:
                    data = json.load(f)
                    return QuarantineState.from_dict(data)
        except Exception as e:
            log.error(f"Failed to load quarantine state: {e}")
        return QuarantineState()
    
    def _save_state(self):
        """Persist quarantine state to disk"""
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_path, 'w') as f:
                json.dump(self.state.to_dict(), f, indent=2)
        except Exception as e:
            log.error(f"Failed to save quarantine state: {e}")
    
    def _load_trust_score(self) -> float:
        """Load trust score from disk"""
        score_path = self.state_path.parent / "trust_score.json"
        try:
            if score_path.exists():
                with open(score_path) as f:
                    data = json.load(f)
                    return data.get("score", 0.0)
        except Exception:
            pass
        return 0.0
    
    def _save_trust_score(self):
        """Save trust score to disk"""
        score_path = self.state_path.parent / "trust_score.json"
        try:
            score_path.parent.mkdir(parents=True, exist_ok=True)
            with open(score_path, 'w') as f:
                json.dump({"score": self.trust_score, "updated_at": time.time()}, f)
        except Exception as e:
            log.error(f"Failed to save trust score: {e}")
    
    def _load_profile_start_time(self) -> float:
        """Load when current profile started"""
        time_path = self.state_path.parent / "profile_start.json"
        try:
            if time_path.exists():
                with open(time_path, encoding="utf-8") as f:
                    data = json.load(f)
                    value = float(data.get("start_time"))
                    if math.isfinite(value) and 0 < value <= time.time() + 300:
                        return value
        except Exception:
            pass
        return time.time()
    
    def _save_profile_start_time(self):
        """Save profile start time"""
        time_path = self.state_path.parent / "profile_start.json"
        try:
            time_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = time_path.with_suffix(time_path.suffix + ".tmp")
            with open(temporary, 'w', encoding="utf-8") as f:
                json.dump({"start_time": self.profile_start_time}, f)
                f.flush()
            temporary.replace(time_path)
        except Exception as e:
            log.error(f"Failed to save profile start time: {e}")
    
    def _ensure_profile_start_time_persisted(self):
        """Persist or repair the durable observation epoch."""
        self._save_profile_start_time()

    def record_error(self):
        """Record an error occurrence"""
        self.error_window.add()
        self._adjust_trust_score(-2.0)
        self._check_quarantine_triggers()
    
    def record_tool_call(self):
        """Record a tool execution"""
        self.tool_window.add()
        self._check_quarantine_triggers()
    
    def record_file_write(self):
        """Record a file write operation"""
        self.write_window.add()
        self._check_quarantine_triggers()
    
    def record_api_call(self):
        """Record an API call"""
        self.api_window.add()
        self._check_quarantine_triggers()
    
    def record_success(self, iterations: int = 1):
        """Record a successful task completion"""
        # Base success score
        score = 1.0
        
        # Efficiency bonus: fewer iterations = better
        if iterations <= 3:
            score += 0.5
        
        self._adjust_trust_score(score)
    
    def _adjust_trust_score(self, delta: float):
        """Adjust trust score and check for profile upgrades"""
        self.trust_score += delta
        self._save_trust_score()
        
        # Check for automatic profile upgrade
        self._check_profile_upgrade()
    
    def _check_quarantine_triggers(self):
        """Check if any quarantine threshold is exceeded"""
        if not self.config.get("quarantine", {}).get("enabled", True):
            return
        
        q = self.config["quarantine"]
        
        # Check error rate
        error_threshold = q.get("error_threshold", {})
        if self.error_window.count() > error_threshold.get("max_errors", 10):
            self._trigger_quarantine("Error rate exceeded threshold")
            return
        
        # Check tool spam
        tool_threshold = q.get("tool_spam_threshold", {})
        if self.tool_window.count() > tool_threshold.get("max_calls", 50):
            self._trigger_quarantine("Tool call rate exceeded threshold")
            return
        
        # Check write spam
        write_threshold = q.get("write_threshold", {})
        if self.write_window.count() > write_threshold.get("max_writes", 30):
            self._trigger_quarantine("File write rate exceeded threshold")
            return
        
        # Check API spam
        api_threshold = q.get("api_threshold", {})
        if self.api_window.count() > api_threshold.get("max_calls", 100):
            self._trigger_quarantine("API call rate exceeded threshold")
            return
    
    def _trigger_quarantine(self, reason: str):
        """Enter quarantine mode"""
        if self.state.in_quarantine:
            return  # Already in quarantine
        
        log.warning(f"🔒 QUARANTINE TRIGGERED: {reason}")
        
        action = self.config.get("quarantine", {}).get("action", "downgrade")
        current_profile = self.get_current_profile()
        
        self.state.in_quarantine = True
        self.state.quarantine_start = time.time()
        self.state.quarantine_reason = reason
        self.state.original_profile = current_profile
        
        self._save_state()
        
        if action == "downgrade":
            log.warning(f"⬇️ Downgrading from {current_profile} to strict profile")
        elif action == "pause":
            log.warning("⏸️ Agent operations paused")
        
        # TODO: Implement notification system
        if self.config.get("quarantine", {}).get("notify", True):
            self._send_notification(reason)
    
    def check_quarantine_release(self) -> bool:
        """Check if quarantine cooldown has expired"""
        if not self.state.in_quarantine:
            return True
        
        cooldown = self.config.get("quarantine", {}).get("cooldown_minutes", 30) * 60
        elapsed = time.time() - self.state.quarantine_start
        
        if elapsed >= cooldown:
            log.info(f"✅ Quarantine released after {elapsed/60:.1f} minutes")
            original = self.state.original_profile or "medium"
            self.state.in_quarantine = False
            self.state.quarantine_start = None
            self.state.quarantine_reason = None
            self._save_state()
            return True
        
        return False
    
    def _check_profile_upgrade(self):
        """Check if agent has earned a profile upgrade"""
        metrics = self.config.get("trust_metrics", {})
        thresholds = metrics.get("upgrade_thresholds", {})
        min_days = metrics.get("min_observation_days", {})
        
        current = self.get_current_profile()
        days_in_profile = (time.time() - self.profile_start_time) / 86400
        
        # Strict → Medium
        if current == "strict":
            required_score = thresholds.get("strict_to_medium", 80)
            required_days = min_days.get("strict_to_medium", 7)
            
            if self.trust_score >= required_score and days_in_profile >= required_days:
                log.info(f"🎉 Trust score {self.trust_score:.1f} - eligible for Medium profile!")
                # Don't auto-upgrade, just log eligibility
        
        # Medium → Loose
        elif current == "medium":
            required_score = thresholds.get("medium_to_loose", 150)
            required_days = min_days.get("medium_to_loose", 14)
            
            if self.trust_score >= required_score and days_in_profile >= required_days:
                log.info(f"🎉 Trust score {self.trust_score:.1f} - eligible for Loose profile!")
    
    def get_current_profile(self) -> Literal["strict", "medium", "loose"]:
        """Get active security profile"""
        if self.state.in_quarantine:
            return "strict"  # Always strict in quarantine
        
        # Read from environment or config
        import os
        return os.environ.get("SECURITY_PROFILE", "strict")
    
    def get_profile_config(self) -> dict:
        """Get configuration for current security profile"""
        profile = self.get_current_profile()
        return self.config.get("profiles", {}).get(profile, {})
    
    def get_status(self) -> dict:
        """Get current monitoring status"""
        return {
            "profile": self.get_current_profile(),
            "in_quarantine": self.state.in_quarantine,
            "quarantine_reason": self.state.quarantine_reason,
            "trust_score": self.trust_score,
            "days_in_profile": (time.time() - self.profile_start_time) / 86400,
            "metrics": {
                "errors_15min": self.error_window.count(),
                "tools_5min": self.tool_window.count(),
                "writes_10min": self.write_window.count(),
                "api_calls_1h": self.api_window.count()
            }
        }
    
    def _send_notification(self, reason: str):
        """Send quarantine notification (placeholder)"""
        # TODO: Integrate with notification system (Telegram, email, etc.)
        pass
