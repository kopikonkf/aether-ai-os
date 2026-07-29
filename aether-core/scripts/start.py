"""
Cross-Platform Launcher for Aether Core
========================================
Replaces Windows-only START.bat with cross-platform Python runner.
"""

import sys
from pathlib import Path

# Add src to path
src_dir = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_dir))

from aether.executive.boot import AetherBoot
from aether.paths import get_paths


def main():
    print("Launching Aether Core...")
    paths = get_paths()
    print(f"AETHER_HOME: {paths.home}")
    
    boot = AetherBoot()
    results = boot.boot()
    print("Boot Results:", results)


if __name__ == "__main__":
    main()
