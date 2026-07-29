"""Read-only application service for Aether's operational MCP surface.

This module intentionally avoids importing the full Gateway composition root.
It reads only bounded operational projections and never creates or mutates
AETHER_HOME state.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

_TOKEN = re.compile(r"[\w-]+", re.UNICODE)
_NAMESPACE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


class MCPPolicyError(ValueError):
    """Raised when an MCP request violates the read-only policy boundary."""


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(
        item.casefold() for item in _TOKEN.findall(text) if len(item) > 1
    ))


def _readonly_connect(path: Path) -> sqlite3.Connection:
    normalized = quote(path.resolve().as_posix(), safe="/:")
    conn = sqlite3.connect(f"file:{normalized}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA busy_timeout=2500")
    return conn


def _safe_json(raw: str | None, fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return fallback


class ReadOnlyMemoryProjection:
    """Bounded read model over canonical and lexical memory SQLite projections."""

    def __init__(
        self,
        canonical_path: Path,
        retrieval_path: Path,
        *,
        maximum_limit: int = 20,
        maximum_content_chars: int = 4000,
    ) -> None:
        self.canonical_path = canonical_path
        self.retrieval_path = retrieval_path
        self.maximum_limit = maximum_limit
        self.maximum_content_chars = maximum_content_chars

    def stats(self) -> dict[str, Any]:
        return {
            "canonical": self._count(self.canonical_path, "memory_records"),
            "retrieval": self._count(self.retrieval_path, "indexed_records"),
        }

    @staticmethod
    def _count(path: Path, table: str) -> dict[str, Any]:
        if not path.is_file():
            return {"available": False, "records": 0, "reason": "database-not-found"}
        try:
            with _readonly_connect(path) as conn:
                row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
            return {"available": True, "records": int(row["n"]), "reason": None}
        except sqlite3.Error as exc:
            return {
                "available": False,
                "records": 0,
                "reason": f"{type(exc).__name__}: {exc}",
            }

    def search(
        self,
        query: str,
        *,
        namespaces: Iterable[str] = ("episodes", "knowledge"),
        limit: int = 6,
        min_score: float = 0.05,
    ) -> dict[str, Any]:
        query = str(query).strip()
        if not query:
            raise MCPPolicyError("query must not be empty")
        if len(query) > 1000:
            raise MCPPolicyError("query exceeds 1000 characters")
        if not 1 <= int(limit) <= self.maximum_limit:
            raise MCPPolicyError(f"limit must be between 1 and {self.maximum_limit}")
        if not 0 <= float(min_score) <= 1:
            raise MCPPolicyError("min_score must be between 0 and 1")

        normalized_namespaces = tuple(dict.fromkeys(
            str(item).strip() for item in namespaces if str(item).strip()
        ))
        if len(normalized_namespaces) > 8 or any(
            not _NAMESPACE.fullmatch(item) for item in normalized_namespaces
        ):
            raise MCPPolicyError("namespaces contain an invalid value")

        terms = _tokens(query)
        if not terms:
            return self._empty_result(
                query, normalized_namespaces, "query-has-no-searchable-terms"
            )
        if not self.canonical_path.is_file() or not self.retrieval_path.is_file():
            return self._empty_result(
                query, normalized_namespaces, "memory-projection-unavailable"
            )

        term_placeholders = ",".join("?" for _ in terms)
        clauses = [f"t.term IN ({term_placeholders})"]
        params: list[Any] = list(terms)
        if normalized_namespaces:
            clauses.append(
                "r.namespace IN (%s)"
                % ",".join("?" for _ in normalized_namespaces)
            )
            params.extend(normalized_namespaces)

        sql = f"""
            SELECT r.record_id, r.token_count, t.term, t.frequency
            FROM memory_terms t
            JOIN indexed_records r ON r.record_id = t.record_id
            WHERE {' AND '.join(clauses)}
        """
        try:
            with _readonly_connect(self.retrieval_path) as conn:
                rows = conn.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            return self._empty_result(
                query,
                normalized_namespaces,
                f"retrieval-error:{type(exc).__name__}",
            )

        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            item = grouped.setdefault(
                str(row["record_id"]),
                {
                    "matched": set(),
                    "frequency": 0,
                    "length": int(row["token_count"] or 0),
                },
            )
            item["matched"].add(str(row["term"]))
            item["frequency"] += int(row["frequency"] or 0)

        ranked: list[tuple[str, float, tuple[str, ...]]] = []
        for record_id, item in grouped.items():
            matched = tuple(sorted(item["matched"]))
            coverage = len(matched) / len(terms)
            density = min(
                1.0,
                item["frequency"] / max(1.0, math.sqrt(item["length"] or 1)),
            )
            score = round(0.8 * coverage + 0.2 * density, 6)
            if score >= float(min_score):
                ranked.append((record_id, score, matched))
        ranked.sort(key=lambda item: (-item[1], item[0]))
        ranked = ranked[: int(limit)]
        if not ranked:
            return self._empty_result(query, normalized_namespaces, None)

        by_id = self._load_records(tuple(item[0] for item in ranked))
        hits: list[dict[str, Any]] = []
        for record_id, score, reasons in ranked:
            row = by_id.get(record_id)
            if row is None:
                continue
            provenance = _safe_json(row["provenance_json"], {})
            content = str(row["content"] or "")
            truncated = len(content) > self.maximum_content_chars
            if truncated:
                content = content[: self.maximum_content_chars] + "…"
            hits.append({
                "record_id": record_id,
                "namespace": str(row["namespace"]),
                "kind": str(row["kind"]),
                "content": content,
                "content_truncated": truncated,
                "content_hash": str(row["content_hash"]),
                "created_at": str(row["created_at"]),
                "score": score,
                "matched_terms": list(reasons),
                "provenance": {
                    "source": provenance.get("source"),
                    "observed_at": provenance.get("observed_at"),
                    "session_id": provenance.get("session_id"),
                    "correlation_id": provenance.get("correlation_id"),
                },
            })

        return {
            "schema": "aether.mcp.memory-search.v1",
            "query": query,
            "namespaces": list(normalized_namespaces),
            "hit_count": len(hits),
            "hits": hits,
            "read_only": True,
            "reason": None,
        }

    def _load_records(self, record_ids: tuple[str, ...]) -> dict[str, sqlite3.Row]:
        if not record_ids:
            return {}
        placeholders = ",".join("?" for _ in record_ids)
        sql = f"""
            SELECT record_id, namespace, kind, content, provenance_json,
                   created_at, content_hash
            FROM memory_records
            WHERE record_id IN ({placeholders})
        """
        try:
            with _readonly_connect(self.canonical_path) as conn:
                rows = conn.execute(sql, record_ids).fetchall()
        except sqlite3.Error:
            return {}
        return {str(row["record_id"]): row for row in rows}

    @staticmethod
    def _empty_result(
        query: str, namespaces: tuple[str, ...], reason: str | None
    ) -> dict[str, Any]:
        return {
            "schema": "aether.mcp.memory-search.v1",
            "query": query,
            "namespaces": list(namespaces),
            "hit_count": 0,
            "hits": [],
            "read_only": True,
            "reason": reason,
        }


class AetherOperationalMCPService:
    """Read-only MCP-facing application service with explicit trust boundaries."""

    schema = "aether.mcp.operational.v1"

    def __init__(self, project_root: Path, aether_home: Path) -> None:
        self.project_root = project_root.expanduser().resolve()
        self.aether_home = aether_home.expanduser().resolve()
        self.memory = ReadOnlyMemoryProjection(
            self.aether_home / "memory" / "canonical-episodes.sqlite3",
            self.aether_home / "memory" / "retrieval-index.sqlite3",
        )

    @classmethod
    def from_environment(cls) -> "AetherOperationalMCPService":
        import os

        detected_root = Path(__file__).resolve().parents[4]
        project_root = Path(os.environ.get("AETHER_PROJECT_ROOT", detected_root))
        home_raw = os.environ.get("AETHER_HOME")
        if home_raw:
            aether_home = Path(home_raw)
        elif os.name == "nt":
            aether_home = (
                Path(os.environ.get(
                    "LOCALAPPDATA", Path.home() / "AppData" / "Local"
                ))
                / "Aether"
            )
        else:
            aether_home = Path.home() / ".aether"
        return cls(project_root, aether_home)

    def status(self) -> dict[str, Any]:
        release = self._read_json(self.project_root / "RELEASE_BUILD.json")
        handoff = self._bounded_text(
            self.project_root / "LASTSTANDINGPOINT.md", maximum_chars=200_000
        )
        return {
            "schema": self.schema,
            "service": "Aether Operational MCP",
            "mode": "read-only",
            "project_root": str(self.project_root),
            "aether_home": str(self.aether_home),
            "aether_home_exists": self.aether_home.is_dir(),
            "release": {
                "release": release.get("release"),
                "build_id": release.get("build_id"),
                "status": release.get("status"),
            },
            "memory": self.memory.stats(),
            "handoff": {
                "available": handoff["available"],
                "sha256": handoff["sha256"],
                "characters": handoff["characters"],
            },
            "security": {
                "mutation_tools": False,
                "approval_decisions": False,
                "arbitrary_file_reads": False,
                "shell": False,
                "legacy_cka_bulk_access": False,
                "remote_http_default": False,
            },
        }

    def capability_manifest(self) -> dict[str, Any]:
        return {
            "schema": "aether.mcp.capability-manifest.v1",
            "server_id": "aether.operational.readonly",
            "authority": "projection-only",
            "resources": [
                {"uri": "aether://status", "classification": "operational"},
                {"uri": "aether://capabilities", "classification": "operational"},
                {"uri": "aether://handoff", "classification": "project-internal"},
            ],
            "tools": [
                {"name": "aether_status", "impact": "read-only"},
                {"name": "aether_capability_manifest", "impact": "read-only"},
                {"name": "aether_handoff", "impact": "read-only"},
                {"name": "memory_search", "impact": "read-only-bounded"},
                {"name": "artifact_hash_verify", "impact": "read-only-bounded"},
            ],
            "prompts": [
                {
                    "name": "aether_operational_context",
                    "authority": "advisory-only",
                    "may_override_system_prompt": False,
                }
            ],
            "transports": {
                "stdio": {"enabled": True, "default": True},
                "streamable-http": {
                    "enabled": "explicit-opt-in",
                    "allowed_hosts": sorted(_LOOPBACK_HOSTS),
                    "public_ingress": False,
                },
            },
            "deferred": [
                "external MCP client manager",
                "remote OAuth",
                "mutation proposal tools",
                "generic MCP Builder",
            ],
        }

    def handoff(self) -> dict[str, Any]:
        result = self._bounded_text(
            self.project_root / "LASTSTANDINGPOINT.md", maximum_chars=200_000
        )
        return {
            "schema": "aether.mcp.handoff.v1",
            "authority": "canonical-repository-handoff",
            **result,
        }

    def memory_search(
        self,
        query: str,
        namespaces: list[str] | None = None,
        limit: int = 6,
        min_score: float = 0.05,
    ) -> dict[str, Any]:
        return self.memory.search(
            query,
            namespaces=tuple(namespaces or ("episodes", "knowledge")),
            limit=limit,
            min_score=min_score,
        )

    def artifact_hash_verify(
        self, path: str, expected_sha256: str | None = None
    ) -> dict[str, Any]:
        raw_path = Path(str(path).strip()).expanduser()
        candidate = raw_path if raw_path.is_absolute() else self.project_root / raw_path
        candidate = candidate.resolve()
        if not self._within_allowed_root(candidate):
            raise MCPPolicyError(
                "path is outside the repository and AETHER_HOME boundaries"
            )
        if not candidate.is_file():
            raise MCPPolicyError("path must identify an existing regular file")
        digest = hashlib.sha256()
        size = 0
        with candidate.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                size += len(chunk)
                digest.update(chunk)
        actual = digest.hexdigest()
        expected = str(expected_sha256 or "").strip().casefold() or None
        if expected is not None and not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise MCPPolicyError(
                "expected_sha256 must be a 64-character hexadecimal digest"
            )
        return {
            "schema": "aether.mcp.artifact-hash.v1",
            "path": str(candidate),
            "size_bytes": size,
            "sha256": actual,
            "expected_sha256": expected,
            "matches": None if expected is None else actual == expected,
            "read_only": True,
        }

    def _within_allowed_root(self, candidate: Path) -> bool:
        for root in (self.project_root, self.aether_home):
            try:
                candidate.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    @staticmethod
    def ensure_loopback_http(host: str, *, enabled: bool) -> None:
        normalized = str(host).strip().casefold()
        if not enabled:
            raise MCPPolicyError(
                "Streamable HTTP requires explicit --enable-http opt-in"
            )
        if normalized not in _LOOPBACK_HOSTS:
            raise MCPPolicyError(
                "Streamable HTTP is restricted to loopback hosts in this baseline"
            )

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _bounded_text(path: Path, *, maximum_chars: int) -> dict[str, Any]:
        if not path.is_file():
            return {
                "available": False,
                "path": str(path),
                "content": "",
                "characters": 0,
                "truncated": False,
                "sha256": None,
                "reason": "file-not-found",
            }
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        text = raw.decode("utf-8", errors="replace")
        truncated = len(text) > maximum_chars
        if truncated:
            text = text[:maximum_chars] + "\n[truncated by Aether MCP policy]"
        return {
            "available": True,
            "path": str(path),
            "content": text,
            "characters": len(text),
            "truncated": truncated,
            "sha256": digest,
            "reason": None,
        }
