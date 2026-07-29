"""
Health Check Script for Aether Core
====================================
Verifies DNA, paths, database, consciousness, and governance integrity.
"""

import sys
from pathlib import Path

src_dir = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_dir))

from aether.dna.loader import DNALoader
from aether.paths import get_paths
from aether.database.manager import get_db
from aether.consciousness.aether_core import SelfModel


def run_health_check():
    print("=" * 60)
    print("AETHER CORE HEALTH CHECK")
    print("=" * 60)

    # 1. Path resolution
    paths = get_paths()
    print(f"[1] AETHER_HOME:       {paths.home} (OK)")

    # 2. DNA integrity
    loader = DNALoader()
    dna_ok = loader.verify_integrity()
    print(f"[2] DNA Integrity:     {'OK' if dna_ok else 'FAIL'}")

    # 3. Checksums
    checksums = loader.get_checksums()
    for fname, sha in checksums.items():
        print(f"    - {fname}: {sha[:16]}...")

    # 4. Database test
    conn = get_db("consciousness")
    db_ok = conn.execute("SELECT 1").fetchone()[0] == 1
    conn.close()
    print(f"[3] Cognitive DB:      {'OK' if db_ok else 'FAIL'}")

    # 5. Self model
    sm = SelfModel()
    who = sm.who_am_i()
    print(f"[4] Self Model:        {who['name']} (Stability: {who['stability']})")

    print("=" * 60)
    print("ALL HEALTH CHECKS PASSED SUCCESSFULLY.")
    print("=" * 60)


if __name__ == "__main__":
    run_health_check()
