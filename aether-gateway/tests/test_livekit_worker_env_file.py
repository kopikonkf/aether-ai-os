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


def _clean_livekit_env(monkeypatch):
    for name in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "AETHER_SENSE_WORKER_TOKEN", "LIVEKIT_AGENT_NAME"):
        monkeypatch.delenv(name, raising=False)


def test_worker_status_from_environment_only(tmp_path, monkeypatch):
    """Review REV7 follow-up: the service runner injects credentials into the
    process environment (role-scoped allowlist, strict parser). The worker must
    NOT accept a second --env-file parser - credentials come from the env the
    runner set. status must reflect the injected values."""
    env_file = tmp_path / "fake-runner-env"
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
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "aether_gateway.browser_senses.worker",
            "status",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "PYTHONPATH": str(ROOT / "aether-gateway" / "src"),
            "LIVEKIT_URL": "wss://synthetic.livekit.cloud",
            "LIVEKIT_API_KEY": "synthetic-key",
            "LIVEKIT_API_SECRET": "synthetic-secret",
            "AETHER_SENSE_WORKER_TOKEN": "synthetic-token",
            "LIVEKIT_AGENT_NAME": "aether-sense-test",
        },
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


def test_worker_status_without_env_reports_not_ready(tmp_path, monkeypatch):
    """Without runner-injected credentials the worker must report not-ready and
    exit non-zero - no silent fallback to an unknown/empty state."""
    _clean_livekit_env(monkeypatch)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "aether_gateway.browser_senses.worker",
            "status",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(ROOT / "aether-gateway" / "src")},
        cwd=ROOT,
    )
    assert result.returncode != 0
    status = json.loads(result.stdout)
    assert status["ready"] is False


def test_worker_rejects_env_file_flag(worker_module_path):
    """Review REV7 follow-up: worker.py must NOT contain a second, weaker
    --env-file credential parser. There is exactly one credential boundary (the
    service runner's strict allowlisted injector)."""
    source = worker_module_path.read_text(encoding="utf-8")
    # No lenient os.environ.setdefault injection (a second, weaker parser).
    assert "os.environ.setdefault" not in source
    # No env-file argument parsing branch in main().
    assert "env_file" not in source.split("def main()", 1)[1]
    # main() derives config straight from the runner-injected environment.
    assert 'LiveKitWorkerConfig.from_env()' in source.split("def main()", 1)[1]


def test_worker_uses_non_deprecated_turn_detector(worker_module_path):
    source = worker_module_path.read_text(encoding="utf-8")
    assert "from livekit.plugins.turn_detector.multilingual import MultilingualModel" not in source
    assert "from livekit.agents.inference import TurnDetector" in source
    assert "TurnDetector()" in source
