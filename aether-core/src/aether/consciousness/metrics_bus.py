"""
Metrics Bus — Rolling Window Metric Collector

Setiap 5 episode: pulse check.
Metric types: gauge, counter, ratio, distribution.

Ring buffer: last 100 data points per metric.
Auto-compute: mean, trend, anomaly detection.
"""
import sqlite3
import json
import time
from pathlib import Path
from datetime import datetime
from collections import deque

from aether.paths import get_paths
DB_DIR = get_paths().db


class MetricSeries:
    """Single metric with rolling window."""

    def __init__(self, name: str, metric_type: str = "gauge", window: int = 100):
        self.name = name
        self.type = metric_type  # gauge, counter, ratio, distribution
        self.window = window
        self.values = deque(maxlen=window)
        self.timestamps = deque(maxlen=window)

    def push(self, value: float, ts: str = None):
        self.values.append(value)
        self.timestamps.append(ts or datetime.now().isoformat())

    def mean(self) -> float:
        return sum(self.values) / len(self.values) if self.values else 0.0

    def latest(self) -> float:
        return self.values[-1] if self.values else 0.0

    def trend(self) -> str:
        """Simple trend: rising, falling, stable."""
        if len(self.values) < 3:
            return "insufficient_data"
        recent = list(self.values)[-5:]
        older = list(self.values)[-10:-5] if len(self.values) >= 10 else list(self.values)[:5]
        r_mean = sum(recent) / len(recent)
        o_mean = sum(older) / len(older)
        delta = r_mean - o_mean
        if abs(delta) < 0.02:
            return "stable"
        return "rising" if delta > 0 else "falling"

    def anomaly(self, threshold: float = 2.0) -> bool:
        """Z-score anomaly detection."""
        if len(self.values) < 5:
            return False
        vals = list(self.values)
        mean = sum(vals) / len(vals)
        variance = sum((v - mean) ** 2 for v in vals) / len(vals)
        std = variance ** 0.5
        if std == 0:
            return False
        z = abs(vals[-1] - mean) / std
        return z > threshold

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "count": len(self.values),
            "latest": round(self.latest(), 4),
            "mean": round(self.mean(), 4),
            "trend": self.trend(),
            "anomaly": self.anomaly()
        }


class MetricsBus:
    """Central metrics collector — rolling window, pulse check."""

    def __init__(self, db_path: str = None):
        self.db_path = str(db_path or DB_DIR / "consciousness.db")
        self.series = {}  # name -> MetricSeries
        self.pulse_interval = 5  # pulse every N episodes
        self.episode_count = 0
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS metrics_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            metric_name TEXT,
            value REAL,
            timestamp TEXT,
            context TEXT DEFAULT '{}'
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS metrics_pulse (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            episode_count INTEGER,
            metrics_snapshot TEXT,
            anomalies TEXT DEFAULT '[]',
            timestamp TEXT
        )''')
        conn.commit()
        conn.close()

    def record(self, name: str, value: float, metric_type: str = "gauge",
               context: dict = None):
        """Record a metric data point."""
        if name not in self.series:
            self.series[name] = MetricSeries(name, metric_type)
        self.series[name].push(value)

        # Persist
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("INSERT INTO metrics_log (metric_name, value, timestamp, context) VALUES (?, ?, ?, ?)",
                 (name, value, datetime.now().isoformat(), json.dumps(context or {})))
        conn.commit()
        conn.close()

    def pulse(self) -> dict:
        """Full pulse check — all metrics snapshot."""
        snapshot = {}
        anomalies = []

        for name, series in self.series.items():
            d = series.to_dict()
            snapshot[name] = d
            if d["anomaly"]:
                anomalies.append(name)

        # Persist pulse
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("INSERT INTO metrics_pulse (episode_count, metrics_snapshot, anomalies, timestamp) VALUES (?, ?, ?, ?)",
                 (self.episode_count, json.dumps(snapshot), json.dumps(anomalies),
                  datetime.now().isoformat()))
        conn.commit()
        conn.close()

        return {
            "episode_count": self.episode_count,
            "metrics": snapshot,
            "anomalies": anomalies,
            "health": "warning" if anomalies else "healthy"
        }

    def should_pulse(self) -> bool:
        """Should we run a pulse check now?"""
        return self.episode_count > 0 and self.episode_count % self.pulse_interval == 0

    def tick_episode(self):
        """Call after each episode completes."""
        self.episode_count += 1

    def get_series(self, name: str) -> dict:
        """Get specific metric series."""
        if name in self.series:
            return self.series[name].to_dict()
        return {"error": f"Metric '{name}' not found"}

    def status(self) -> dict:
        return {
            "tracked_metrics": len(self.series),
            "episode_count": self.episode_count,
            "pulse_interval": self.pulse_interval,
            "next_pulse_at": self.pulse_interval - (self.episode_count % self.pulse_interval),
            "metrics": {name: s.to_dict() for name, s in self.series.items()}
        }


def demo():
    bus = MetricsBus()
    import random
    for i in range(12):
        bus.record("prediction_accuracy", 0.5 + random.uniform(-0.1, 0.1))
        bus.record("belief_count", 80 + i * 2)
        bus.record("surprise_score", random.uniform(0.1, 0.8))
        bus.tick_episode()
        if bus.should_pulse():
            pulse = bus.pulse()
            print(f"Episode {bus.episode_count}: pulse={pulse['health']}, anomalies={pulse['anomalies']}")
    print(json.dumps(bus.status(), indent=2))


if __name__ == "__main__":
    demo()
