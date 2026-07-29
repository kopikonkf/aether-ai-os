from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from aether_gateway.mcp.service import AetherOperationalMCPService, MCPPolicyError


def _service(tmp_path: Path) -> AetherOperationalMCPService:
    project = tmp_path / "project"
    home = tmp_path / "aether-home"
    project.mkdir()
    (project / "RELEASE_BUILD.json").write_text(
        json.dumps({"release": "0.19.2", "build_id": "test-build", "status": "test"}),
        encoding="utf-8",
    )
    (project / "LASTSTANDINGPOINT.md").write_text(
        "# Current\n\nMCP baseline test.\n", encoding="utf-8"
    )
    return AetherOperationalMCPService(project, home)


def _seed_memory(home: Path) -> None:
    memory = home / "memory"
    memory.mkdir(parents=True)
    canonical = memory / "canonical-episodes.sqlite3"
    retrieval = memory / "retrieval-index.sqlite3"
    with sqlite3.connect(canonical) as conn:
        conn.executescript(
            """
            CREATE TABLE memory_records (
                record_id TEXT PRIMARY KEY,
                record_key TEXT NOT NULL,
                namespace TEXT NOT NULL,
                kind TEXT NOT NULL,
                value_json TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                provenance_json TEXT,
                created_at TEXT NOT NULL,
                content_hash TEXT NOT NULL UNIQUE
            );
            """
        )
        conn.execute(
            "INSERT INTO memory_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "mem.001",
                "turn.001",
                "episodes",
                "episode",
                "{}",
                "Founder accepted the Windows laptop baseline.",
                "{}",
                json.dumps({
                    "source": "telegram",
                    "observed_at": "2026-07-29T00:00:00Z",
                }),
                "2026-07-29T00:00:00Z",
                "a" * 64,
            ),
        )
    with sqlite3.connect(retrieval) as conn:
        conn.executescript(
            """
            CREATE TABLE indexed_records (
                record_id TEXT PRIMARY KEY,
                namespace TEXT NOT NULL,
                content TEXT NOT NULL,
                token_count INTEGER NOT NULL
            );
            CREATE TABLE memory_terms (
                term TEXT NOT NULL,
                record_id TEXT NOT NULL,
                frequency INTEGER NOT NULL,
                PRIMARY KEY(term, record_id)
            );
            """
        )
        conn.execute(
            "INSERT INTO indexed_records VALUES (?, ?, ?, ?)",
            (
                "mem.001",
                "episodes",
                "Founder accepted the Windows laptop baseline.",
                6,
            ),
        )
        conn.executemany(
            "INSERT INTO memory_terms VALUES (?, ?, ?)",
            [
                (term, "mem.001", 1)
                for term in (
                    "founder",
                    "accepted",
                    "windows",
                    "laptop",
                    "baseline",
                )
            ],
        )


def test_status_is_read_only_for_fresh_home(tmp_path: Path) -> None:
    service = _service(tmp_path)
    assert not service.aether_home.exists()

    status = service.status()

    assert status["mode"] == "read-only"
    assert status["release"]["build_id"] == "test-build"
    assert status["security"]["mutation_tools"] is False
    assert not service.aether_home.exists(), (
        "read-only status must not create AETHER_HOME"
    )


def test_handoff_has_authoritative_digest(tmp_path: Path) -> None:
    service = _service(tmp_path)
    expected = hashlib.sha256(
        (service.project_root / "LASTSTANDINGPOINT.md").read_bytes()
    ).hexdigest()

    handoff = service.handoff()

    assert handoff["available"] is True
    assert handoff["sha256"] == expected
    assert "MCP baseline test" in handoff["content"]


def test_memory_search_reads_existing_projections_without_sidecars(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    _seed_memory(service.aether_home)
    before = sorted(
        path.relative_to(service.aether_home).as_posix()
        for path in service.aether_home.rglob("*")
    )

    result = service.memory_search("Founder Windows baseline")

    after = sorted(
        path.relative_to(service.aether_home).as_posix()
        for path in service.aether_home.rglob("*")
    )
    assert result["hit_count"] == 1
    assert result["hits"][0]["record_id"] == "mem.001"
    assert result["hits"][0]["provenance"]["source"] == "telegram"
    assert before == after
    assert not any(
        path.suffix in {".wal", ".shm"}
        for path in service.aether_home.rglob("*")
    )


def test_artifact_verification_is_root_bounded(tmp_path: Path) -> None:
    service = _service(tmp_path)
    artifact = service.project_root / "artifact.txt"
    artifact.write_text("aether", encoding="utf-8")
    digest = hashlib.sha256(b"aether").hexdigest()

    result = service.artifact_hash_verify("artifact.txt", digest)

    assert result["matches"] is True
    with pytest.raises(MCPPolicyError, match="outside"):
        service.artifact_hash_verify(str(tmp_path / "outside.txt"))


def test_http_requires_opt_in_and_loopback() -> None:
    with pytest.raises(MCPPolicyError, match="explicit"):
        AetherOperationalMCPService.ensure_loopback_http(
            "127.0.0.1", enabled=False
        )
    with pytest.raises(MCPPolicyError, match="loopback"):
        AetherOperationalMCPService.ensure_loopback_http(
            "0.0.0.0", enabled=True
        )
    AetherOperationalMCPService.ensure_loopback_http(
        "localhost", enabled=True
    )
