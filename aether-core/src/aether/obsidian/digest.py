from __future__ import annotations

from pathlib import Path
from typing import Any

from aether.utils.ids import new_id
from aether.obsidian.notes import write_note


def write_source_digest(
    root: Path,
    title: str,
    summary: str,
    claims: list[str],
    source_uri: str | None = None,
) -> dict[str, Any]:
    source_id = new_id("source")
    digest_id = new_id("digest")
    claim_lines = "\n".join(f"- {claim}" for claim in claims) or "- No claims supplied."
    body = f"""# Digest - {title}

## Source
{source_uri or 'manual'}

## Summary
{summary}

## Key Claims
{claim_lines}

## Candidate Beliefs
- Review claims and promote only when evidence is sufficient.

## Follow-up
- Validate source quality.
- Search for contradictions.
"""
    return write_note(
        root,
        "digest",
        f"Digest - {title}",
        body,
        metadata={"source_id": source_id, "digest_id": digest_id, "source_uri": source_uri, "claims": claims, "tags": ["sniper/digest", "sniper/source"]},
        folder="04_Digests",
        overwrite=False,
    )


def write_belief_note(root: Path, claim: str, confidence: float = 0.30, maturity: str = "candidate") -> dict[str, Any]:
    body = f"""# Belief - {claim}

## Claim
{claim}

## Evidence
- Evidence not linked yet.

## Contradictions
- No contradictions reviewed yet.

## Current Confidence
{confidence}

## Next Test
- Find supporting and contradicting evidence.
"""
    return write_note(
        root,
        "belief",
        f"Belief - {claim[:80]}",
        body,
        metadata={"claim": claim, "confidence": confidence, "maturity": maturity, "tags": ["sniper/belief", f"maturity/{maturity}"]},
        folder="06_Beliefs",
        overwrite=False,
    )
