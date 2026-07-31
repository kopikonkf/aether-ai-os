"""Canonical Aether runtime paths."""
from __future__ import annotations

import os
import platform
from pathlib import Path


def get_aether_home() -> Path:
    """Return the mutable-state root for Aether."""
    env = os.environ.get("AETHER_HOME")
    if env:
        return Path(env)
    if platform.system() == "Windows":
        return Path("C:/aether/home")
    return Path.home() / ".aether"


class AetherHome:
    """Small path helper for mutable runtime artifacts."""

    def __init__(self, root: Path | str | None = None):
        self.root = Path(root) if root is not None else get_aether_home()

    @property
    def runtime(self) -> Path:
        return self.root / "runtime"

    @property
    def body(self) -> Path:
        return self.runtime / "body"

    @property
    def receipts(self) -> Path:
        return self.body / "receipts.jsonl"

    @property
    def latest_receipt(self) -> Path:
        return self.body / "latest_receipt.json"

    @property
    def budget_state(self) -> Path:
        return self.body / "budget_state.json"

    @property
    def tts(self) -> Path:
        return self.body / "tts"

    @property
    def tts_auditions(self) -> Path:
        return self.tts / "auditions"

    @property
    def founder_acceptance(self) -> Path:
        return self.runtime / "founder_acceptance"

    @property
    def founder_acceptance_packet(self) -> Path:
        return self.founder_acceptance / "latest_packet.json"

    @property
    def founder_acceptance_record(self) -> Path:
        return self.founder_acceptance / "latest_acceptance.json"

    @property
    def founder_acceptance_log(self) -> Path:
        return self.founder_acceptance / "acceptance.jsonl"

    @property
    def mcp(self) -> Path:
        return self.runtime / "mcp"

    @property
    def mcp_manifest(self) -> Path:
        return self.mcp / "manifest.json"

    @property
    def mcp_latest_activation(self) -> Path:
        return self.mcp / "latest_activation.json"

    @property
    def mcp_receipts(self) -> Path:
        return self.mcp / "receipts.jsonl"

    @property
    def releases(self) -> Path:
        return self.runtime / "releases"

    @property
    def mvp20_release(self) -> Path:
        return self.releases / "mvp_v0_20"

    @property
    def mvp20_latest_packet(self) -> Path:
        return self.mvp20_release / "latest_packet.json"

    @property
    def mvp20_log(self) -> Path:
        return self.mvp20_release / "release_packets.jsonl"

    def ensure(self) -> None:
        self.body.mkdir(parents=True, exist_ok=True)
        self.tts_auditions.mkdir(parents=True, exist_ok=True)
        self.founder_acceptance.mkdir(parents=True, exist_ok=True)
        self.mcp.mkdir(parents=True, exist_ok=True)
        self.mvp20_release.mkdir(parents=True, exist_ok=True)
