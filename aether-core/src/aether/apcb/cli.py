"""APCB Slice B — one-shot dispatch CLI (deterministic local bridge).

Usage:
    python -m aether.apcb.cli --work-id WORK-1 --mission MISSION-1 \
        --principal qwen --workspace workspace://default \
        --objective "implement x" --capability coding \
        --receipts <path.jsonl> [--attempt 1] [--authorized] [--ready] \
        [--wait 300]

The CLI wires the real components (profile registry, receipt store,
conformance gate with the live herdr CLI probe, Herdr execution adapter) and
prints a bounded DispatchDecision. It never invents policy: authorization and
execution-ready flags must be passed explicitly by the caller.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from aether.apcb.conformance import ConformanceGate
from aether.apcb.dispatcher import APCBDispatcher
from aether.apcb.eligibility import WorkItemView
from aether.apcb.herdr_adapter import (
    HerdrExecutionAdapter,
    PaneUniquenessError,
    validate_pane_map_unique,
)
from aether.apcb.profiles import load_principal_profiles
from aether.apcb.receipt_store import ReceiptStore


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--work-id", required=True)
    p.add_argument("--mission", required=True)
    p.add_argument("--principal", required=True)
    p.add_argument("--workspace", required=True)
    p.add_argument("--profile", required=True, help="explicit herdr:* execution profile for this work item")
    p.add_argument("--objective", default="")
    p.add_argument("--capability", action="append", default=[])
    p.add_argument("--receipts", required=True, help="path to append-only receipt JSONL")
    p.add_argument("--registry", default=None, help="principal_runtime_profiles.yaml path")
    p.add_argument("--attempt", type=int, default=1)
    p.add_argument("--authorized", action="store_true")
    p.add_argument("--ready", action="store_true")
    p.add_argument("--wait", type=float, default=300.0)
    p.add_argument("--reconcile", action="store_true", help="reconcile existing receipt, do not dispatch")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    profiles = load_principal_profiles(Path(args.registry) if args.registry else None)
    receipts = ReceiptStore(Path(args.receipts))
    adapter = HerdrExecutionAdapter()
    gate = ConformanceGate(profiles, probe=adapter.detect_adapter)

    # K4 — pane uniqueness validator (WORK-5 blocker): fail-closed before any
    # dispatch. Sovereign principals must never share a pane in a no-message-bus
    # design where pane identity is part of authority.
    try:
        validate_pane_map_unique()
    except PaneUniquenessError as exc:
        print(json.dumps({
            "work_id": args.work_id,
            "mission_id": args.mission,
            "principal_id": args.principal,
            "attempt_number": args.attempt,
            "dispatched": False,
            "status": "rejected",
            "diagnostic": [f"pane uniqueness gate: {exc}"],
        }, indent=2, ensure_ascii=False))
        return 1

    work = WorkItemView(
        work_id=args.work_id,
        mission_id=args.mission,
        principal_id=args.principal,
        required_capabilities=tuple(args.capability),
        workspace_id=args.workspace,
        authorized=args.authorized,
        execution_ready=args.ready,
        awaiting_approval=False,
        attempt_number=args.attempt,
        execution_profile=args.profile,
        metadata={"objective": args.objective},
    )

    dispatcher = APCBDispatcher(
        profiles=profiles,
        receipts=receipts,
        conformance_gate=gate,
        adapter=adapter,
        wait_timeout_seconds=args.wait,
    )

    if args.reconcile:
        decision = dispatcher.reconcile(work)
    else:
        decision = dispatcher.dispatch(work)

    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps(decision.to_dict(), indent=2, ensure_ascii=False))
    return 0 if decision.dispatched else 1


if __name__ == "__main__":
    sys.exit(main())
