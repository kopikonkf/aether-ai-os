#!/usr/bin/env python3
"""Copy mutable state into AETHER_HOME without rewriting historical records."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path, help="Existing mutable-state directory")
    parser.add_argument("--target", required=True, type=Path, help="New AETHER_HOME directory")
    parser.add_argument("--apply", action="store_true", help="Perform copy; otherwise print plan")
    args = parser.parse_args()

    source = args.source.expanduser().resolve()
    target = args.target.expanduser().resolve()
    if not source.is_dir():
        raise SystemExit(f"Source does not exist: {source}")
    if source == target or source in target.parents:
        raise SystemExit("Target must be separate from source")

    print(f"source={source}")
    print(f"target={target}")
    print("Historical content is preserved verbatim; only its storage boundary changes.")
    if not args.apply:
        print("dry-run: pass --apply to copy")
        return 0

    shutil.copytree(source, target, dirs_exist_ok=True, copy_function=shutil.copy2)
    print("state migration complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
