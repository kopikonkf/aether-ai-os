from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _sdk_installed(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def test_livekit_extras_are_installed():
    """The [livekit] extra resolves the exact pinned SDK and is import-safe."""
    assert _sdk_installed("livekit.agents")
    assert _sdk_installed("livekit.api")
    assert _sdk_installed("livekit.plugins.silero")


def test_turn_detector_is_built_in_not_plugin():
    """livekit.agents.inference.TurnDetector must be importable and instantiable.
    The deprecated livekit-plugins-turn-detector must not be a dependency."""
    from livekit.agents.inference import TurnDetector

    detector = TurnDetector()
    assert detector is not None
    pyproject = (ROOT / "aether-gateway" / "pyproject.toml").read_text(encoding="utf-8")
    assert "turn-detector" not in pyproject
    assert "turn_detector" not in pyproject


def test_pinned_livekit_versions_resolve():
    from importlib.metadata import version

    assert version("livekit-agents") == "1.6.9"
    assert version("livekit-api") == "1.2.0"
    assert version("livekit-plugins-silero") == "1.6.9"
