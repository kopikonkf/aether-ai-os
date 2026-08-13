"""APCB Slice B — one-shot dispatch CLI (deterministic local bridge).

Usage:
    python -m aether.apcb.cli --work-id WORK-1 --mission MISSION-1 \
        --principal qwen --workspace workspace://default \
        --objective "implement x" --capability coding \
        --receipts <path.jsonl> [--attempt 1] [--authorized] [--ready] \
        [--wait 300] [--mission-state running] \
        [--expected-artifact WORK-PCP-003.md]

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
    p.add_argument(
        "--mission-state",
        default=None,
        help="canonical Aether mission state string for reconcile (e.g. running/completed/failed); "
        "omit to leave observation-level 'unknown'",
    )
    p.add_argument(
        "--expected-artifact",
        default=None,
        help="filename that must exist (non-empty) in the workspace for a 'completed' terminal "
        "(ADR-0057 artifact authority); e.g. WORK-PCP-003.md",
    )
    return p


def _build_workspace_verify(workspace_id: str | None):
    """Build a workspace-binding verifier when the workspace is a real directory.

    APCB observes bound workspaces (contract §8); the gate only verifies that a
    directory-form workspace exists on disk so dispatch can proceed. Returns
    None for URI-style or empty workspace refs (no binding gate).
    """
    if not workspace_id or "://" in workspace_id:
        return None
    try:
        if not Path(workspace_id).is_dir():
            return None
    except OSError:
        return None

    def verify(ws: str) -> bool:
        try:
            return Path(ws).is_dir()
        except OSError:
            return False

    return verify


def parse_artifact_envelope(text: str, limit_lines: int = 60) -> dict[str, str]:
    """Parse the canonical envelope header from an artifact's first lines.

    The worker writes the same canonical header the prompt carried (see
    _render_prompt in dispatcher.py): lines like 'protocol: aether.apcb.task.v1',
    'work_id: WORK-1', 'principal_id: qwen', 'attempt: 1'. Returns a mapping of
    the header keys found within the first `limit_lines`; a placeholder or
    stale artifact without the envelope yields an empty/partial mapping.
    """
    header: dict[str, str] = {}
    for line in text.splitlines()[:limit_lines]:
        line = line.strip()
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key:
            header[key] = value
    return header


def _build_artifact_verify(expected_artifact: str | None):
    """Build an ADR-0057 artifact-authority verifier from --expected-artifact.

    The verifier (F-01/F-02) requires BOTH that the named artifact exists in
    the workspace and is non-empty, AND that its canonical envelope header
    matches the work item (work_id, principal_id, attempt_number). A 1-byte
    placeholder or a stale artifact from a different attempt is rejected.
    Returns None when no artifact is expected (no artifact gate).
    """
    if not expected_artifact:
        return None
    name = expected_artifact.strip()
    if not name:
        return None

    def verify(work: WorkItemView) -> bool:
        try:
            ws = work.workspace_id or ""
            p = Path(ws) / name
            if not (p.is_file() and p.stat().st_size > 0):
                return False
            header = parse_artifact_envelope(p.read_text("utf-8", errors="replace"))
            if header.get("work_id") != work.work_id:
                return False
            if header.get("principal_id") != work.principal_id:
                return False
            if header.get("attempt") != str(work.attempt_number):
                return False
            return True
        except OSError:
            return False

    return verify


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
        aether_state_observer=(
            (lambda mission_id: args.mission_state) if args.mission_state else None
        ),
        workspace_verify=_build_workspace_verify(args.workspace),
        artifact_verify=_build_artifact_verify(args.expected_artifact),
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
