"""Canonical governed work_mapper for mission -> APCB work items.

MISSION-PCP-002 WORK-2: default mapper that derives principal_id,
execution_profile, workspace_id and required_capabilities from canonical
mission action metadata + the Aether principal profile registry, fail-closed
when nothing is assigned.

This mapper is GOVERNED: it never guesses. Every decision is derived either
from the mission step action's canonical metadata (set by the orchestrator /
live runner) or from the Founder-owned PrincipalRuntimeProfiles registry. A
field that cannot be assigned is left empty so the APCB EligibilityEvaluator
rejects the work item with a readable blocker (principal_assigned False /
profile_enabled False), never raising mid-mapping.

Canonical metadata keys (carried on ActionProposal.metadata):
  - mission_principal_id      (required) principal that runs the step
  - mission_execution_profile (optional) explicit profile; else derived
  - mission_workspace_id      (required for live) workspace binding
  - mission_capabilities      (optional tuple) required capabilities
  - mission_authorized        (optional, default True) mission pre-approved
  - mission_execution_ready   (optional, default True)
  - mission_awaiting_approval (optional)
  - mission_work_id           (optional) overrides derived WORK-{action_id}
  - mission_expected_artifact (optional) expected deliverable filename; the
    ADR-0057 artifact authority verifier checks it against the workspace
  - mission_id, mission_attempt_number (set by the orchestrator)

Legacy aliases: workspace_id, awaiting_approval.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Mapping

from aether.apcb.cli import parse_artifact_envelope
from aether.apcb.eligibility import WorkItemView
from aether.apcb.profiles import PrincipalRuntimeProfiles
from aether.contracts.actions import ActionProposal

# Canonical mission-action metadata keys.
MISSION_PRINCIPAL_ID = "mission_principal_id"
MISSION_EXECUTION_PROFILE = "mission_execution_profile"
MISSION_WORKSPACE_ID = "mission_workspace_id"
MISSION_CAPABILITIES = "mission_capabilities"
MISSION_AUTHORIZED = "mission_authorized"
MISSION_EXECUTION_READY = "mission_execution_ready"
MISSION_AWAITING_APPROVAL = "mission_awaiting_approval"
MISSION_WORK_ID = "mission_work_id"
MISSION_ATTEMPT_NUMBER = "mission_attempt_number"
MISSION_ID = "mission_id"
MISSION_EXPECTED_ARTIFACT = "mission_expected_artifact"

# Legacy / plain aliases tolerated for compatibility.
_LEGACY_WORKSPACE_ID = "workspace_id"
_LEGACY_AWAITING_APPROVAL = "awaiting_approval"

# Optional, local operation -> capability hint used only when
# mission_capabilities is empty. Default stays empty when un-mapped.
_OPERATION_CAPABILITY: Mapping[str, str] = {
    "implement": "coding",
    "refactor": "refactoring",
    "test": "testing",
    "verify": "verification",
}

# Deterministic filename hints for build_expected_artifact_from_criteria.
_ARTIFACT_EXTENSIONS = (".md", ".json", ".txt", ".py", ".jsonl")
_ARTIFACT_PREFIXES = ("WORK-", "mission_")
_WORD_TOKEN = re.compile(r"[\w][\w\-.]*")


def build_expected_artifact_from_criteria(
    success_criteria: tuple[str, ...],
) -> str | None:
    """Derive an expected artifact filename from success criteria (HINT).

    Deterministic heuristic: scan every criterion and return the first token
    that looks like a filename — a token with one of the known extensions
    (.md/.json/.txt/.py/.jsonl) OR starting with WORK- / mission_. Returns None
    when nothing matches. This is a HINT, not free-form parsing: callers that
    need an exact artifact should set mission_expected_artifact explicitly.
    """
    for criterion in success_criteria or ():
        for token in _WORD_TOKEN.findall(str(criterion)):
            lowered = token.lower()
            if lowered.endswith(_ARTIFACT_EXTENSIONS):
                return token
            if lowered.startswith(_ARTIFACT_PREFIXES):
                return token
    return None


def build_mission_artifact_verify(
    expected_artifact: str | None,
) -> Callable[[WorkItemView], bool] | None:
    """Build the mission-level ADR-0057 artifact verifier (WorkItemView-based).

    Reuses the canonical envelope parser (aether.apcb.cli.parse_artifact_envelope)
    and enforces the same authority rules as the CLI verifier: the named
    artifact must exist in the work item's workspace, be non-empty, and its
    envelope header must match the work item on all five identity fields
    (protocol, mission_id, work_id, principal_id, attempt). A 1-byte placeholder,
    a stale artifact from another attempt, or an artifact produced under another
    mission is rejected. Returns None when no artifact is expected (no artifact
    gate).
    """
    if not expected_artifact:
        return None
    name = str(expected_artifact).strip()
    if not name:
        return None

    def verify(work: WorkItemView) -> bool:
        try:
            ws = work.workspace_id or ""
            p = Path(ws) / name
            if not (p.is_file() and p.stat().st_size > 0):
                return False
            header = parse_artifact_envelope(p.read_text("utf-8", errors="replace"))
            if header.get("protocol") != "aether.apcb.task.v1":
                return False
            if header.get("mission_id") != work.mission_id:
                return False
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


def _derive_execution_profile(
    profiles: PrincipalRuntimeProfiles, principal_id: str, requested: str | None
) -> str:
    """Return the explicit profile when valid, else the principal's first
    registered execution profile; empty string when nothing is assignable."""
    principal = profiles.get_principal(principal_id)
    if principal is None:
        return ""
    if requested and profiles.principal_has_profile(principal_id, requested):
        return requested
    for name in principal.execution_profiles:
        if name in profiles.execution_profiles:
            return name
    return ""


def build_canonical_work_mapper(
    profiles: PrincipalRuntimeProfiles,
) -> Callable[[ActionProposal, int], WorkItemView]:
    """Return a governed work_mapper bound to a profile registry.

    The returned callable maps (proposal, attempt) -> WorkItemView, deriving
    every field from canonical mission metadata + the registry. It NEVER raises
    for un-assigned fields; unassignable fields stay empty so APCB eligibility
    rejects with a readable blocker (fail-closed by design).
    """

    def mapper(action: ActionProposal, attempt: int) -> WorkItemView:
        meta: Mapping[str, Any] = dict(action.metadata or {})
        principal_id = str(meta.get(MISSION_PRINCIPAL_ID) or "")
        profile = _derive_execution_profile(
            profiles,
            principal_id,
            str(meta.get(MISSION_EXECUTION_PROFILE) or "") or None,
        )
        workspace_id = str(
            meta.get(MISSION_WORKSPACE_ID) or meta.get(_LEGACY_WORKSPACE_ID) or ""
        )
        capabilities = tuple(meta.get(MISSION_CAPABILITIES) or ())
        if not capabilities:
            # G6-B: a per-principal step (no explicit mission_capabilities) requires
            # exactly the capabilities its OWN principal is registered with — never
            # an inherited directive capability the principal lacks. Fall back to the
            # operation hint only when the principal is not registered.
            principal = profiles.get_principal(principal_id)
            if principal is not None and principal.capabilities:
                capabilities = tuple(sorted(principal.capabilities))
            else:
                hint = _OPERATION_CAPABILITY.get(action.operation or "")
                capabilities = (hint,) if hint else ()
        work_meta = dict(meta)
        if meta.get(MISSION_EXPECTED_ARTIFACT) is not None:
            work_meta[MISSION_EXPECTED_ARTIFACT] = meta[MISSION_EXPECTED_ARTIFACT]
        return WorkItemView(
            work_id=str(meta.get(MISSION_WORK_ID) or f"WORK-{action.action_id}"),
            mission_id=str(meta.get(MISSION_ID) or ""),
            principal_id=principal_id,
            required_capabilities=capabilities,
            workspace_id=workspace_id,
            authorized=bool(meta.get(MISSION_AUTHORIZED, True)),
            execution_ready=bool(meta.get(MISSION_EXECUTION_READY, True)),
            awaiting_approval=bool(
                meta.get(MISSION_AWAITING_APPROVAL)
                or meta.get(_LEGACY_AWAITING_APPROVAL)
            ),
            attempt_number=attempt,
            execution_profile=profile,
            metadata=work_meta,
        )

    return mapper
