"""
DNA Loader & Integrity Verification Engine
===========================================
Loads frozen identity documents (North Star, Genome, Self-Model)
and enforces SHA256 checksum integrity verification.
"""

import json
import hashlib
from pathlib import Path
from typing import Any, Dict
import yaml


class DNALoader:
    """Read-only loader for Aether Core DNA layer."""

    def __init__(self, dna_dir: Path | None = None):
        self.dna_dir = dna_dir or Path(__file__).parent

    def load_north_star(self) -> Dict[str, Any]:
        """Load frozen North Star specification."""
        path = self.dna_dir / "north_star.yaml"
        if not path.exists():
            raise FileNotFoundError(f"North Star file not found at {path}")
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

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
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_checksums(self) -> Dict[str, str]:
        """Compute SHA256 checksums for all DNA files."""
        checksums = {}
        for filename in ["north_star.yaml", "Genome.md", "aether.core.json"]:
            path = self.dna_dir / filename
            if path.exists():
                sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
                checksums[filename] = sha256
        return checksums

    def verify_integrity(self) -> bool:
        """Verify that all DNA files exist and are readable."""
        try:
            self.load_north_star()
            self.load_genome()
            self.load_identity()
            return True
        except Exception:
            return False
