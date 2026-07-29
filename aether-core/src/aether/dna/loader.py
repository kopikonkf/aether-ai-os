"""
DNA Loader & Integrity Verification Engine
===========================================
Loads frozen identity documents (North Star, Genome, Self-Model) and verifies
all canonical DNA files against a Founder-reviewed SHA-256 manifest.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict

import yaml


class DNALoader:
    """Read-only loader for Aether Core DNA layer."""

    MANIFEST_FILENAME = "integrity_manifest.json"
    DNA_FILENAMES = ("north_star.yaml", "Genome.md", "aether.core.json")
    MANIFEST_SCHEMA = "aether.dna.integrity-manifest.v1"

    def __init__(self, dna_dir: Path | None = None):
        self.dna_dir = (dna_dir or Path(__file__).parent).resolve()

    def load_north_star(self) -> Dict[str, Any]:
        """Load frozen North Star specification."""
        path = self.dna_dir / "north_star.yaml"
        if not path.exists():
            raise FileNotFoundError(f"North Star file not found at {path}")
        with path.open("r", encoding="utf-8") as handle:
            value = yaml.safe_load(handle)
        if not isinstance(value, dict):
            raise ValueError("North Star must decode to a mapping")
        return value

    def load_genome(self) -> str:
        """Load frozen Genome.md text."""
        path = self.dna_dir / "Genome.md"
        if not path.exists():
            raise FileNotFoundError(f"Genome file not found at {path}")
        return path.read_text(encoding="utf-8")

    def load_identity(self) -> Dict[str, Any]:
        """Load Hard Authority Self-Model JSON."""
        path = self.dna_dir / "aether.core.json"
        if not path.exists():
            raise FileNotFoundError(f"Identity file not found at {path}")
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise ValueError("Identity self-model must decode to a mapping")
        return value

    def load_manifest(self) -> Dict[str, Any]:
        """Load and validate the versioned DNA integrity manifest."""
        path = self.dna_dir / self.MANIFEST_FILENAME
        if not path.exists():
            raise FileNotFoundError(f"DNA integrity manifest not found at {path}")
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise ValueError("DNA integrity manifest must decode to a mapping")
        if value.get("schema") != self.MANIFEST_SCHEMA:
            raise ValueError("Unsupported DNA integrity manifest schema")
        if value.get("algorithm") != "sha256":
            raise ValueError("DNA integrity manifest must use sha256")
        files = value.get("files")
        if not isinstance(files, dict):
            raise ValueError("DNA integrity manifest files must be a mapping")
        return value

    def get_checksums(self) -> Dict[str, str]:
        """Compute SHA-256 checksums for all canonical DNA files that exist."""
        checksums: Dict[str, str] = {}
        for filename in self.DNA_FILENAMES:
            path = self.dna_dir / filename
            if path.is_file():
                checksums[filename] = hashlib.sha256(path.read_bytes()).hexdigest()
        return checksums

    def integrity_report(self) -> Dict[str, Any]:
        """Return file-level evidence for manifest-backed DNA verification."""
        report: Dict[str, Any] = {
            "schema": "aether.dna.integrity-report.v1",
            "dna_dir": str(self.dna_dir),
            "manifest": self.MANIFEST_FILENAME,
            "ok": False,
            "errors": [],
            "files": {},
        }

        try:
            manifest = self.load_manifest()
        except Exception as exc:
            report["errors"].append(
                f"manifest: {type(exc).__name__}: {exc}"
            )
            return report

        manifest_files = manifest["files"]
        expected_names = set(self.DNA_FILENAMES)
        manifested_names = set(manifest_files)
        if manifested_names != expected_names:
            missing = sorted(expected_names - manifested_names)
            unexpected = sorted(manifested_names - expected_names)
            if missing:
                report["errors"].append(
                    f"manifest missing canonical files: {', '.join(missing)}"
                )
            if unexpected:
                report["errors"].append(
                    f"manifest contains unexpected files: {', '.join(unexpected)}"
                )

        loaders = {
            "north_star.yaml": self.load_north_star,
            "Genome.md": self.load_genome,
            "aether.core.json": self.load_identity,
        }

        for filename in self.DNA_FILENAMES:
            path = self.dna_dir / filename
            manifest_entry = manifest_files.get(filename)
            expected_sha256 = (
                str(manifest_entry.get("sha256", "")).casefold()
                if isinstance(manifest_entry, dict)
                else ""
            )
            item: Dict[str, Any] = {
                "path": str(path),
                "exists": path.is_file(),
                "readable": False,
                "parse_ok": False,
                "expected_sha256": expected_sha256 or None,
                "actual_sha256": None,
                "matches": False,
                "error": None,
            }

            if not item["exists"]:
                item["error"] = "file-not-found"
                report["errors"].append(f"{filename}: file-not-found")
                report["files"][filename] = item
                continue

            try:
                raw = path.read_bytes()
                item["readable"] = True
                item["actual_sha256"] = hashlib.sha256(raw).hexdigest()
            except OSError as exc:
                item["error"] = f"{type(exc).__name__}: {exc}"
                report["errors"].append(f"{filename}: {item['error']}")
                report["files"][filename] = item
                continue

            try:
                loaders[filename]()
                item["parse_ok"] = True
            except Exception as exc:
                item["error"] = f"parse-error: {type(exc).__name__}: {exc}"
                report["errors"].append(f"{filename}: {item['error']}")

            if len(expected_sha256) != 64 or any(
                char not in "0123456789abcdef" for char in expected_sha256
            ):
                item["error"] = "manifest-sha256-invalid"
                report["errors"].append(
                    f"{filename}: manifest-sha256-invalid"
                )
            else:
                item["matches"] = item["actual_sha256"] == expected_sha256
                if not item["matches"]:
                    item["error"] = "sha256-mismatch"
                    report["errors"].append(f"{filename}: sha256-mismatch")

            report["files"][filename] = item

        report["ok"] = not report["errors"] and all(
            item["exists"]
            and item["readable"]
            and item["parse_ok"]
            and item["matches"]
            for item in report["files"].values()
        )
        return report

    def verify_integrity(self) -> bool:
        """Return true only when every canonical DNA file matches the manifest."""
        return bool(self.integrity_report()["ok"])
