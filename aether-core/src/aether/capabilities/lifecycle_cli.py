"""CLI for recording observation-derived capability lifecycle evidence.

ADR-0055 prerequisite P4: Living Machine MCP mutation path reaches
FOUNDER-PROVEN for a single principal before a second principal is
authorized against the same mutation surface.

This CLI records lifecycle transitions with explicit evidence markers. It is
NOT a governance authority — every stage still requires real observation
evidence to be passed in, and the state machine refuses to advance without it.

Usage:
    aether-capability-lifecycle --home <AETHER_HOME> \
        --surface living-mcp.mutation --principal chatgpt \
        --to-stage wired --evidence runtime_constructed --evidence path_reachable
    aether-capability-lifecycle --home <AETHER_HOME> --status
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from aether.capabilities.lifecycle import (
    KNOWN_MUTATION_SURFACES,
    MUTATION_SURFACE_LIVING_MCP,
    STAGES,
    CapabilityLifecycle,
    CapabilityLifecycleBlocked,
)
from aether.runtime.paths import get_aether_home


def _log_path(home: Path) -> Path:
    return home / "runtime" / "capability_lifecycle" / "lifecycle.jsonl"


def _print_status(lc: CapabilityLifecycle) -> int:
    print(json.dumps(lc.surface_state(MUTATION_SURFACE_LIVING_MCP), indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record capability lifecycle evidence (ADR-0055 P4)")
    parser.add_argument("--home", default=None, help="Aether home (default: AETHER_HOME env or platform default)")
    parser.add_argument("--surface", default=MUTATION_SURFACE_LIVING_MCP, choices=sorted(KNOWN_MUTATION_SURFACES))
    parser.add_argument("--principal", default="chatgpt")
    parser.add_argument("--to-stage", choices=STAGES)
    parser.add_argument("--evidence", action="append", default=[], help="evidence marker id (repeatable)")
    parser.add_argument("--note", default=None)
    parser.add_argument("--status", action="store_true", help="print current lifecycle state and exit")
    args = parser.parse_args(argv)

    home = Path(args.home) if args.home else Path(get_aether_home())
    lc = CapabilityLifecycle(_log_path(home))

    if args.status:
        return _print_status(lc)
    if not args.to_stage:
        parser.error("--to-stage is required unless --status is used")

    evidence = {key: True for key in args.evidence}
    try:
        record = lc.advance(
            surface=args.surface,
            principal_id=args.principal,
            to_stage=args.to_stage,
            evidence=evidence,
            note=args.note,
        )
    except CapabilityLifecycleBlocked as exc:
        print("BLOCKED: " + "; ".join(exc.blockers), file=sys.stderr)
        return 2

    print(json.dumps(record.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
