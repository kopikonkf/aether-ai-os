from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def worker_module_path():
    return ROOT / "aether-gateway" / "src" / "aether_gateway" / "browser_senses" / "worker.py"


def test_worker_status_env_file_loads_synthetic_values(tmp_path, monkeypatch):
    """The --env-file flag is consumed by main(); status must reflect the loaded
    values even when the env-file is the only source of LiveKit credentials."""
    env_file = tmp_path / "sense-worker.env"
    env_file.write_text(
        "\n".join(
            [
                "LIVEKIT_URL=wss://synthetic.livekit.cloud",
                "LIVEKIT_API_KEY=synthetic-key",
                "LIVEKIT_API_SECRET=synthetic-secret",
                "AETHER_SENSE_WORKER_TOKEN=synthetic-token",
                "LIVEKIT_AGENT_NAME=aether-sense-test",
            ]
        ),
        encoding="utf-8",
    )
    for name in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "AETHER_SENSE_WORKER_TOKEN", "LIVEKIT_AGENT_NAME"):
        monkeypatch.delenv(name, raising=False)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "aether_gateway.browser_senses.worker",
            "status",
            "--env-file",
            str(env_file),
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(ROOT / "aether-gateway" / "src")},
        cwd=ROOT,
    )
    assert result.returncode == 0, f"status exited {result.returncode}: {result.stderr[:500]}"
    status = json.loads(result.stdout)
    assert status["config"]["worker_token"] == "<configured>"
    assert status["config"]["agent_name"] == "aether-sense-test"
    assert status["livekit_environment"] == {
        "LIVEKIT_URL": True,
        "LIVEKIT_API_KEY": True,
        "LIVEKIT_API_SECRET": True,
    }


def test_worker_status_missing_env_file_reports_error(tmp_path, monkeypatch):
    """When the --env-file path does not exist, main() must print an error and
    exit non-zero — no silent fallback to empty/unknown state."""
    for name in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "AETHER_SENSE_WORKER_TOKEN", "LIVEKIT_AGENT_NAME"):
        monkeypatch.delenv(name, raising=False)
    nonexistent = tmp_path / "does-not-exist.env"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "aether_gateway.browser_senses.worker",
            "status",
            "--env-file",
            str(nonexistent),
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(ROOT / "aether-gateway" / "src")},
        cwd=ROOT,
    )
    assert result.returncode != 0
    assert "error" in (result.stdout + result.stderr).lower()


def test_worker_uses_non_deprecated_turn_detector(worker_module_path):
    source = worker_module_path.read_text(encoding="utf-8")
    assert "from livekit.plugins.turn_detector.multilingual import MultilingualModel" not in source
    assert "from livekit.agents.inference import TurnDetector" in source
    assert "TurnDetector()" in source