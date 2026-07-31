"""CLI wrapper for the Founder acceptance gate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from aether.runtime.body import ConformedRuntimeBody, FounderAcceptanceRequest, RuntimeBodyConfig


def _load_json(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    return dict(json.loads(Path(path).read_text(encoding="utf-8")))


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate or record Aether Founder acceptance.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="Print the current Founder acceptance packet.")
    status.add_argument("--evidence-json", help="Optional evidence JSON file to merge into the packet.")

    accept = subparsers.add_parser("accept", help="Record an explicit Founder acceptance.")
    accept.add_argument("--founder-id", required=True)
    accept.add_argument("--attestation", required=True)
    accept.add_argument("--scope", default="mvp-v0.20-preflight")
    accept.add_argument("--evidence-json", help="Optional evidence JSON file.")
    accept.add_argument("--allow-pending-evidence", action="store_true")

    args = parser.parse_args()
    body = ConformedRuntimeBody(RuntimeBodyConfig.from_env())
    evidence = _load_json(getattr(args, "evidence_json", None))

    if args.command == "status":
        result = body.founder_acceptance_packet(evidence=evidence)
    else:
        result = body.accept_founder_packet(
            FounderAcceptanceRequest(
                founder_id=args.founder_id,
                attestation=args.attestation,
                scope=args.scope,
                evidence=evidence,
                allow_pending_evidence=args.allow_pending_evidence,
            )
        )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
